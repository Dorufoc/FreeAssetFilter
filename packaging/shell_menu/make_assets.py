"""从 assets/Sopeek.png 生成 MSIX 所需的图标资源（一次性 / 可重跑）。"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "assets" / "Sopeek.png"
TARGET = Path(__file__).resolve().parent / "Assets"

SIZES = [
    (44, "Square44x44Logo.png"),
    (88, "Square44x44Logo.scale-200.png"),
    (150, "Square150x150Logo.png"),
    (300, "Square150x150Logo.scale-200.png"),
    (50, "StoreLogo.png"),
    (100, "StoreLogo.scale-200.png"),
]

# 任务栏按钮的图标由包的 VisualElements 资源解析（带包标识运行时不再使用窗口
# 图标），而 Windows 11 的托盘/任务栏只按 targetsize + altform-unplated 这组
# 限定名去找小尺寸图；只放一张 44x44 会让按钮显示成空白方块。
TRAY_SIZES = (16, 24, 32, 48, 256)
TRAY_FORMS = ("", "altform-unplated", "altform-lightunplated")


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    source = Image.open(SOURCE).convert("RGBA")
    for size, name in SIZES:
        source.resize((size, size), Image.LANCZOS).save(TARGET / name)
        print(f"wrote {name} ({size}x{size})")

    for size in TRAY_SIZES:
        for form in TRAY_FORMS:
            suffix = f"_{form}" if form else ""
            name = f"Square44x44Logo.targetsize-{size}{suffix}.png"
            source.resize((size, size), Image.LANCZOS).save(TARGET / name)
            print(f"wrote {name} ({size}x{size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
