# -*- coding: utf-8 -*-
"""
集成测试配置和fixtures
"""

import sys
import pytest
from pathlib import Path

# 添加项目根目录到 sys.path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def qapp():
    """提供 QApplication 实例"""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont
    from freeassetfilter.core.settings_manager import SettingsManager
    from freeassetfilter.core.theme_manager import ThemeManager
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.dpi_scale_factor = 1.0
    app.global_font = QFont("Microsoft YaHei", 9)
    # 设置 settings_manager，避免组件初始化时 AttributeError
    if not hasattr(app, 'settings_manager'):
        app.settings_manager = SettingsManager()
    # 设置 theme_manager
    if not hasattr(app, 'theme_manager'):
        app.theme_manager = ThemeManager()
    yield app


@pytest.fixture
def file_selector(qapp):
    """提供 CustomFileSelector 实例"""
    from freeassetfilter.components.file_selector import CustomFileSelector
    widget = CustomFileSelector()
    yield widget
    widget.close()
    widget.deleteLater()


@pytest.fixture
def unified_previewer(qapp):
    """提供 UnifiedPreviewer 实例"""
    from freeassetfilter.components.unified_previewer import UnifiedPreviewer
    widget = UnifiedPreviewer()
    yield widget
    widget.close()
    widget.deleteLater()


@pytest.fixture
def video_player(qapp):
    """提供 VideoPlayer 实例"""
    from freeassetfilter.components.video_player import VideoPlayer
    player = VideoPlayer()
    yield player
    player.cleanup(async_mode=False)
    player.close()
    player.deleteLater()


@pytest.fixture
def file_staging_pool(qapp):
    """提供 FileStagingPool 实例"""
    from freeassetfilter.components.file_staging_pool import FileStagingPool
    widget = FileStagingPool()
    yield widget
    widget.close()
    widget.deleteLater()


@pytest.fixture
def settings_window(qapp):
    """提供 ModernSettingsWindow 实例"""
    from freeassetfilter.components.settings_window import ModernSettingsWindow
    window = ModernSettingsWindow()
    yield window
    window.close()
    window.deleteLater()


@pytest.fixture
def sample_file_info(tmp_path):
    """提供示例文件信息字典"""
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")
    return {
        "name": "test.txt",
        "path": str(test_file),
        "is_dir": False,
        "size": test_file.stat().st_size,
        "modified": "",
        "created": "",
        "suffix": "txt",
    }


@pytest.fixture
def sample_dir_info(tmp_path):
    """提供示例目录信息字典"""
    test_dir = tmp_path / "test_folder"
    test_dir.mkdir()
    return {
        "name": "test_folder",
        "path": str(test_dir),
        "is_dir": True,
        "size": 0,
        "modified": "",
        "created": "",
        "suffix": "",
    }


@pytest.fixture
def qt_app(qapp):
    """qt_app 是 qapp 的别名，兼容旧测试"""
    yield qapp


@pytest.fixture
def sample_image_data():
    """提供简单的 RGBA 图像数据用于颜色提取测试"""
    from PIL import Image
    import io
    img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def temp_data_dir(tmp_path):
    """提供临时数据目录"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def settings_manager(tmp_path):
    """提供使用临时文件的 SettingsManager 实例"""
    from freeassetfilter.core.settings_manager import SettingsManager
    settings_file = tmp_path / "test_settings.json"
    SettingsManager._instance = None
    SettingsManager._initialized = False
    manager = SettingsManager(settings_file=str(settings_file))
    yield manager
    SettingsManager._instance = None
    SettingsManager._initialized = False


@pytest.fixture
def temp_svg_file(tmp_path):
    """提供临时 SVG 文件"""
    svg_content = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
  <rect fill="#000000" width="24" height="24"/>
</svg>'''
    svg_file = tmp_path / "test.svg"
    svg_file.write_text(svg_content, encoding="utf-8")
    return str(svg_file)


@pytest.fixture
def temp_file(tmp_path):
    """提供临时文件"""
    test_file = tmp_path / "test_file.txt"
    test_file.write_text("test content")
    return str(test_file)


@pytest.fixture
def settings_file(tmp_path):
    """提供临时设置文件路径"""
    return str(tmp_path / "settings.json")


@pytest.fixture(scope="function")
def heartbeat_manager(qapp):
    """Create a fresh HeartbeatManager singleton for testing.

    Resets the singleton between tests to ensure test isolation.
    The qapp fixture ensures QApplication exists for QObject creation.
    """
    from freeassetfilter.core.heartbeat_manager import HeartbeatManager

    HeartbeatManager._instance = None
    HeartbeatManager._initialized = False
    hm = HeartbeatManager()
    hm.start()
    yield hm
    hm.stop_all()
    HeartbeatManager._instance = None
    HeartbeatManager._initialized = False


@pytest.fixture
def temp_settings_file(tmp_path):
    """提供带内容的临时设置文件"""
    settings_data = {
        "appearance": {
            "theme": "dark",
            "colors": {
                "accent_color": "#FF0000",
                "base_color": "#f1f3f5",
                "secondary_color": "#333333",
                "normal_color": "#CECECE",
                "auxiliary_color": "#DDDDDD",
                "custom_design_color": "#AABBCC",
            },
        },
        "font": {
            "size": 12,
        },
    }
    settings_file = tmp_path / "temp_settings.json"
    import json
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(settings_data, f)
    return str(settings_file)


# =============================================================================
# 新添加 fixtures — 程序化测试数据生成器、MPV 检测、单体重置
# =============================================================================


@pytest.fixture(autouse=True, scope="function")
def reset_singletons():
    """在每个测试函数前自动重置全局单例，保证测试隔离性。

    重置以下管理器的单例状态：
    - SettingsManager: _instance / _initialized
    - HeartbeatManager: _instance / _initialized

    与 heartbeat_manager / settings_manager fixture 兼容：
    这些 fixture 在自身 setup/teardown 中也会重置，
    额外的空重置是幂等的，不会造成破坏。
    """
    from freeassetfilter.core.settings_manager import SettingsManager
    from freeassetfilter.core.heartbeat_manager import HeartbeatManager
    SettingsManager._instance = None
    SettingsManager._initialized = False
    HeartbeatManager._instance = None
    HeartbeatManager._initialized = False


@pytest.fixture
def temp_image_file(tmp_path):
    """使用 PIL 创建多种格式的测试图片文件。

    创建 PNG (RGBA)、JPEG (RGB)、BMP (RGB) 三种格式，
    每张图片包含简单的彩色图案（不同颜色的几何图形），
    用于缩略图生成、颜色提取、图像预览等功能的测试。

    Returns:
        list[str]: [png_path, jpg_path, bmp_path] 三个路径字符串
    """
    from PIL import Image, ImageDraw

    paths = []

    # PNG RGBA — 蓝色半透明圆形在透明背景上
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([10, 10, 90, 90], fill=(0, 100, 255, 200))
    p = tmp_path / "test.png"
    img.save(p, "PNG")
    paths.append(str(p))

    # JPEG RGB — 红色矩形 + 绿色三角形
    img = Image.new("RGB", (100, 100), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 90, 90], fill=(220, 40, 40))
    draw.polygon([(50, 10), (10, 90), (90, 90)], fill=(40, 200, 40))
    p = tmp_path / "test.jpg"
    img.save(p, "JPEG")
    paths.append(str(p))

    # BMP RGB — 水平渐变色带
    img = Image.new("RGB", (100, 100))
    for y in range(100):
        for x in range(100):
            img.putpixel((x, y), (x * 2 % 256, y * 2 % 256, 128))
    p = tmp_path / "test.bmp"
    img.save(p, "BMP")
    paths.append(str(p))

    return paths


@pytest.fixture
def temp_pdf_file(tmp_path):
    """使用纯字节构造创建一个最小可用的 PDF 文件。

    不依赖任何外部 PDF 库（fpdf2/reportlab），
    直接构造符合 PDF 1.4 规范的字节内容。
    包含一页 "Hello World" 文本（Helvetica 24pt）。

    Returns:
        str: PDF 文件路径
    """
    # Build PDF objects incrementally
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n")
    obj4 = (b"4 0 obj\n<< /Length 44 >>\nstream\n"
            b"BT /F1 24 Tf 100 700 Td (Hello World) Tj ET\nendstream\nendobj\n")
    obj5 = b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"

    objects = [obj1, obj2, obj3, obj4, obj5]

    header = b"%PDF-1.4\n"
    body = b"".join(objects)

    # Calculate byte offsets for xref table
    offsets = []
    pos = len(header)
    for obj in objects:
        offsets.append(pos)
        pos += len(obj)

    xref_offset = pos
    num_entries = len(objects) + 1  # +1 for free entry (obj 0)
    xref_parts = [f"xref\n0 {num_entries}\n".encode()]
    xref_parts.append(b"0000000000 65535 f \n")
    for offset in offsets:
        xref_parts.append(f"{offset:010d} 00000 n \n".encode())
    xref = b"".join(xref_parts)

    trailer = f"trailer\n<< /Size {num_entries} /Root 1 0 R >>\n".encode()
    startxref = f"startxref\n{xref_offset}\n%%EOF".encode()

    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(header + body + xref + trailer + startxref)
    return str(pdf_path)


@pytest.fixture
def temp_text_file(tmp_path):
    """创建三种常见文本格式的测试文件。

    创建 txt / md / json 各一个：
    - txt: 纯文本，三行内容
    - md: 带 Markdown 格式的文档
    - json: 有效 JSON 数据

    Returns:
        list[str]: [txt_path, md_path, json_path]
    """
    import json

    # TXT
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("Hello, World!\nLine 2\nLine 3", encoding="utf-8")

    # MD
    md_path = tmp_path / "test.md"
    md_path.write_text(
        "# Title\n\nContent with **bold** and *italic*", encoding="utf-8"
    )

    # JSON
    json_path = tmp_path / "test.json"
    json_path.write_text(
        json.dumps({"key": "value", "number": 42, "list": [1, 2, 3]}, indent=2),
        encoding="utf-8",
    )

    return [str(txt_path), str(md_path), str(json_path)]


@pytest.fixture
def temp_archive_zip(tmp_path):
    """使用 zipfile 标准库创建一个测试 ZIP 压缩包。

    压缩包内包含 2 个内部文件：
    - hello.txt: 文本内容
    - subdir/data.json: 子目录中的 JSON 数据

    Returns:
        str: ZIP 文件路径
    """
    import zipfile

    zip_path = tmp_path / "test_archive.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("hello.txt", "Hello from ZIP archive!")
        zf.writestr(
            "subdir/data.json",
            '{"name": "test", "value": 42}',
        )
    return str(zip_path)


@pytest.fixture
def temp_font_file(tmp_path):
    """尝试创建临时字体文件用于字体预览测试。

    优先从 Windows 系统字体目录复制一个 TTF 字体作为样本。
    如果系统字体不可访问或文件不存在，返回 None。
    使用 PIL 的 ImageFont.load_default() 验证字体系统可用性。

    Returns:
        str | None: 字体文件路径，如果不可用则返回 None
    """
    import shutil

    font_path = tmp_path / "test_font.ttf"
    windows_fonts = Path("C:/Windows/Fonts")
    candidates = [
        windows_fonts / "arial.ttf",
        windows_fonts / "Arial.ttf",
        windows_fonts / "segoeui.ttf",
        windows_fonts / "SegoeUI.ttf",
        windows_fonts / "tahoma.ttf",
        windows_fonts / "Tahoma.ttf",
        windows_fonts / "msyh.ttc",
        windows_fonts / "msyh.ttf",
    ]
    for candidate in candidates:
        if candidate.exists():
            shutil.copy2(str(candidate), str(font_path))
            return str(font_path)

    # Fallback: 验证 PIL 字体系统是否工作
    try:
        from PIL import ImageFont
        ImageFont.load_default()
    except Exception:
        pass
    return None


@pytest.fixture
def sample_file_dict(tmp_path, request):
    """返回符合标准 file_info 格式的字典。

    创建一个临时文件并返回其信息字典，
    可通过 parametrize 的 extension 参数指定不同后缀（默认 "png"）：

    Usage:
        @pytest.mark.parametrize("sample_file_dict", ["jpg", "pdf", "txt"], indirect=True)
        def test_something(sample_file_dict):
            assert sample_file_dict["suffix"] == "jpg"

    Returns:
        dict: {
            "name": str,
            "path": str,
            "is_dir": False,
            "size": int,
            "modified": str,
            "created": str,
            "suffix": str,
        }
    """
    ext = getattr(request, "param", "png")
    file_path = tmp_path / f"test.{ext}"
    file_path.write_text("dummy content for file info dict")

    return {
        "name": f"test.{ext}",
        "path": str(file_path),
        "is_dir": False,
        "size": 1234,
        "modified": "2024-01-15 10:30:00",
        "created": "2024-01-15 10:30:00",
        "suffix": ext,
    }


@pytest.fixture(scope="session")
def mpv_available():
    """检测 libmpv-2.dll 是否可加载（session scope）。

    使用 ctypes.CDLL 尝试从系统库路径和常见位置加载：
        1. 系统 PATH / LD_LIBRARY_PATH
        2. freeassetfilter/core/ 目录
        3. 应用根目录

    从不抛出异常 — 加载失败时返回 False。

    Returns:
        bool: libmpv-2.dll 可加载则为 True，否则为 False。
    """
    import ctypes

    # 首先尝试系统默认加载
    try:
        ctypes.CDLL("libmpv-2.dll")
        return True
    except OSError:
        pass

    # 搜索项目内部可能的位置
    project_root = Path(__file__).parent.parent
    search_dirs = [
        project_root / "freeassetfilter" / "core",
        project_root,
        project_root / "freeassetfilter",
    ]

    for dll_base in ("libmpv-2.dll", "libmpv.dll"):
        for search_dir in search_dirs:
            candidate = search_dir / dll_base
            if candidate.is_file():
                try:
                    ctypes.CDLL(str(candidate))
                    return True
                except OSError:
                    continue

    return False

