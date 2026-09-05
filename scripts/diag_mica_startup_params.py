# -*- coding: utf-8 -*-
"""诊断脚本：复现 main_window.py 启动流程，检查 Mica 视觉参数是否正确应用。"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJ = r"D:\Temps\yaoshi\Desktop\code\FreeAssetFilter"
sys.path.insert(0, os.path.join(PROJ, "freeassetfilter", "ui"))
sys.path.insert(0, PROJ)

# 1) 先看磁盘上的持久化值
v2_path = os.path.join(PROJ, "data", "settings_v2.json")
disk = json.load(open(v2_path, encoding="utf-8"))["appearance"]["mica"]
print("[disk] appearance.mica =", disk)

# 2) 静态加载器返回值
from PySide6.QtWidgets import QApplication
app = QApplication([])

from freeassetfilter.ui.main_window import MainWindow
loaded = MainWindow._load_mica_settings()
print("[loader] MainWindow._load_mica_settings() =", loaded)

# 3) 实例化主窗口，跟踪参数流转
win = MainWindow()
print("[win] _blur_radius =", win._blur_radius)
print("[win] _saturation  =", win._saturation)
print("[win] _contrast    =", win._contrast)
print("[win] _tint_opacity=", win._tint_opacity)

bg = win._mica_background
print("[bg] type =", type(bg).__name__)
print("[bg] _blur_radius =", getattr(bg, "_blur_radius", None))
print("[bg] _saturation  =", getattr(bg, "_saturation", None))
print("[bg] _contrast    =", getattr(bg, "_contrast", None))
print("[bg] _tint_opacity=", getattr(bg, "_tint_opacity", None))

mica = getattr(bg, "_mica", None)
if mica is not None:
    p = mica._params
    print("[mica] _params =", p)
    print("[mica] _overlay_opacity =", mica._overlay_opacity)
    eng = p.to_engine(mica._dark)
    print("[mica] engine(sigma,gain,cap_scale,alpha) =",
          round(eng.sigma, 2), round(eng.gain, 3), round(eng.cap_scale, 3), round(eng.alpha, 2))
else:
    print("[mica] None !")

# 4) 模拟启动后的 refresh_async 调度（showEvent 里的逻辑）
print("[showEvent guard] _mica_refresh_started =", getattr(win, "_mica_refresh_started", False),
      "background_mode =", win._background_mode)
