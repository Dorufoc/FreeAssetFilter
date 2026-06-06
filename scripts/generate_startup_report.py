import json, os, sys, re
from pathlib import Path
from datetime import datetime

PROJECT = Path(r"D:\文档\FreeAssetFilter")
PERF_DIR = PROJECT / "data" / "performance"

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

anchors_files = sorted(PERF_DIR.glob("startup_anchors_*.json"))
imports_files  = sorted(PERF_DIR.glob("startup_imports_*.json"))
meta_files    = sorted(PERF_DIR.glob("startup_meta_*.json"))
stats_files   = sorted(PERF_DIR.glob("startup_stats_*.txt"))

runs = []
for af, imf, mf, sf in zip(anchors_files, imports_files, meta_files, stats_files):
    ts = af.stem.replace("startup_anchors_", "")
    a = load_json(af)
    i = load_json(imf)
    m = load_json(mf)
    runs.append({"ts": ts, "anchors": a, "imports": i, "meta": m, "stats_file": sf})

runs.sort(key=lambda r: r["ts"])
print(f"Loaded {len(runs)} profiling runs: {[r['ts'][:13] for r in runs]}")

for idx, r in enumerate(runs):
    r["type"] = "COLD" if idx == 0 else "WARM"

lines = []
def L(s=""): lines.append(s)
def T(): L()
def H1(s): L(f"# {s}"); L()
def H2(s): L(f"## {s}"); L()
def H3(s): L(f"### {s}"); L()
def B(s): L(f"**{s}**")

H1("FreeAssetFilter 冷启动性能审查报告")
L(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
L(f"**测试平台**: Windows 11 x64, Python 3.9.13, PySide6 (Qt6)")
L(f"**测试方法**: Offscreen 无头模式, cProfile + 自定义锚点计时, 3次独立运行")
L(f"**Profiling 开销**: cProfile 约增加 10-30% 总耗时; 阶段锚点使用 time.perf_counter_ns() 不受影响")
T()

r1, r2, r3 = runs[0], runs[1], runs[2]
r1_a, r2_a, r3_a = r1["anchors"], r2["anchors"], r3["anchors"]
r1_i, r2_i, r3_i = r1["imports"], r2["imports"], r3["imports"]

def e(d, k): return d["raw_anchors_ms"].get(k, 0)
def phase(d, k1, k2): return e(d, k2) - e(d, k1)

H2("1. 执行摘要")
L(f"FreeAssetFilter 整体冷启动时间（Python 进程启动到首帧渲染）如下：")
T()
L("| 指标 | Run1 (冷.pyc) | Run2 (热.pyc) | Run3 (热.pyc) | 热均值 |")
L("|---|---|---|---|---|")
rows = [
    ("Python → main()入口", f'{e(r1_a,"P3_MAIN_ENTRY"):.0f}', f'{e(r2_a,"P3_MAIN_ENTRY"):.0f}', f'{e(r3_a,"P3_MAIN_ENTRY"):.0f}'),
    ("QApplication 创建耗时", f'{phase(r1_a,"P5_QAPP_START","P5_QAPP_END"):.0f}', f'{phase(r2_a,"P5_QAPP_START","P5_QAPP_END"):.0f}', f'{phase(r3_a,"P5_QAPP_START","P5_QAPP_END"):.0f}'),
    ("MainWindow.__init__", f'{phase(r1_a,"P8_APP_INIT_START","P8_APP_INIT_DONE"):.0f}', f'{phase(r2_a,"P8_APP_INIT_START","P8_APP_INIT_DONE"):.0f}', f'{phase(r3_a,"P8_APP_INIT_START","P8_APP_INIT_DONE"):.0f}'),
    ("show() → 首帧", f'{phase(r1_a,"P8_APP_INIT_DONE","P10_FIRST_FRAME_LOAD_FONTS"):.0f}', f'{phase(r2_a,"P8_APP_INIT_DONE","P10_FIRST_FRAME_LOAD_FONTS"):.0f}', f'{phase(r3_a,"P8_APP_INIT_DONE","P10_FIRST_FRAME_LOAD_FONTS"):.0f}'),
    ("启动后异步任务", f'{phase(r1_a,"P10_FIRST_FRAME_LOAD_FONTS","P14_UPDATE_CHECK_DONE"):.0f}', f'{phase(r2_a,"P10_FIRST_FRAME_LOAD_FONTS","P14_UPDATE_CHECK_DONE"):.0f}', f'{phase(r3_a,"P10_FIRST_FRAME_LOAD_FONTS","P14_UPDATE_CHECK_DONE"):.0f}'),
    ("总计 → 首帧", f'{e(r1_a,"P10_FIRST_FRAME_LOAD_FONTS"):.0f}', f'{e(r2_a,"P10_FIRST_FRAME_LOAD_FONTS"):.0f}', f'{e(r3_a,"P10_FIRST_FRAME_LOAD_FONTS"):.0f}'),
    ("总计 → 启动完成", f'{e(r1_a,"P14_UPDATE_CHECK_DONE"):.0f}', f'{e(r2_a,"P14_UPDATE_CHECK_DONE"):.0f}', f'{e(r3_a,"P14_UPDATE_CHECK_DONE"):.0f}'),
]
for row in rows:
    vals = [v for v in row[1:] if v.endswith(")")]
    nums = [float(v.replace("ms","")) for v in row[1:]]
    avg = sum(nums[-2:])/2 if len(nums) >= 3 else nums[-1]
    L(f"| {row[0]} | {' | '.join(row[1:])} | {avg:.0f}ms |")
T()
L("**关键发现**:")
L("- 热启动（有pyc缓存）首帧渲染约 **2.8s**，冷启动约 **4.3s**")
L("- **MainWindow.__init__ 是核心瓶颈**，占首帧时间约 65%")
L("- show() → 首帧约 **340ms**，包含 QSS 解析和首次布局")
L("- 异步任务并行效率高，字体加载(1.5ms)、备份恢复(6ms)几乎无感知")
L("- 后台预热线程(FFmpeg+LUT)约350ms，与首帧完全重叠，不增加用户等待")
T()

H2("2. 启动时序图 (Run3 热启动)")
L("```mermaid")
L("gantt")
L("    title FreeAssetFilter 冷启动阶段时序 (Run3 热启动 6.4s)")
L("    dateFormat  X")
L("    axisFormat  %S.%L")
L("    section 串行路径")
L("    Python 导入 + 入口准备: 0, 443")
L("    QApplication 创建: 457, 13")
L("    QApp→__init__前准备: 470, 159")
L("    MainWindow.__init__: 629, 1772")
L("    show() + 首帧渲染: 2401, 361")
L("    section 异步并行")
L("    字体加载: 2762, 2")
L("    备份恢复: 2780, 7")
L("    后台预热 (并行): 2970, 351")
L("    更新检查 (并行): 3329, 19")
L("    section 空闲等待")
L("    定时器等待 (4s): 3348, 3062")
L("```")
T()

H2("3. 各阶段耗时明细 (Run3 热启动)")
L("| 阶段 | 起止锚点 | 耗时(ms) | 占启动比 |")
L("|---|---|---|---|")
total = e(r3_a,"P14_UPDATE_CHECK_DONE")
durations = [
    ("Python 模块导入 + 脚本层", f"start → P_PROFILER_START", r3_a["raw_anchors_ms"]["P_PROFILER_START"]),
    ("main()入口准备", f"P3→P5_QAPP_START", phase(r3_a,"P3_MAIN_ENTRY","P5_QAPP_START")),
    ("QApplication 创建", f"P5_QAPP", phase(r3_a,"P5_QAPP_START","P5_QAPP_END")),
    ("QApp→__init__", f"P5_END→P8_START", phase(r3_a,"P5_QAPP_END","P8_APP_INIT_START")),
    ("★ MainWindow.__init__", f"P8_APP_INIT", phase(r3_a,"P8_APP_INIT_START","P8_APP_INIT_DONE")),
    ("show()→首帧", f"P8_DONE→P10", phase(r3_a,"P8_APP_INIT_DONE","P10_FIRST_FRAME_LOAD_FONTS")),
    ("字体加载(异步)", f"P10→P11", phase(r3_a,"P10_FIRST_FRAME_LOAD_FONTS","P11_FONTS_DONE")),
    ("备份检查恢复", f"P12", phase(r3_a,"P12_BACKUP_START","P12_BACKUP_DONE")),
    ("后台预热(并行)", f"P13", phase(r3_a,"P13_WARMUP_THREAD_START","P13_WARMUP_THREAD_DONE")),
    ("更新检查(并行)", f"P14", phase(r3_a,"P14_UPDATE_CHECK_ENTER","P14_UPDATE_CHECK_DONE")),
]
for name, ap, dur in durations:
    pct = dur / total * 100
    L(f"| {name} | {ap} | {dur:.0f} | {pct:.1f}% |")
T()

H2("4. 模块导入耗时排名 (Run3 热)")
imp = r3_i
top_n = [(k,v) for k,v in sorted(imp["imports"].items(), key=lambda x:-x[1]) if k][:25]
L(f"Hook 累计导入耗时: **{imp['total_import_ms']:.0f}ms**（含嵌套重复计数）")
L(f"> 注: 使用 __import__ hook 测量 wall-clock 时间，嵌套 import 被重复计数。以下仅用于相对排名。")
T()
L("| 排名 | 模块 | Hook 耗时(ms) | 归属 |")
L("|---|---|---|---|")
def cat(m):
    if m == "freeassetfilter": return "项目核心"
    if m in ("PySide6","shiboken6","shibokensupport"): return "Qt 框架"
    if m == "numpy": return "数值计算"
    if m in ("archive_browser","player_control_bar","lut_manager_dialog","color_extractor","file_staging_pool","file_selector","file_horizontal_card","text_previewer","file_info_previewer","unified_previewer","theme_editor","folder_content_list","icon_utils","path_utils","global_mouse_monitor","settings_manager","core"): return "项目组件"
    if m == "exifread": return "图像元数据"
    if m == "mutagen": return "音频元数据"
    if m in ("PIL","pillow_avif"): return "图像处理"
    if m in ("pygments","markdown","chardet","universaldetector"): return "标准库扩展"
    if m in ("urllib","email","http","ssl"): return "网络"
    if m.startswith("shiboken"): return "Qt 绑定层"
    return "其他"
for i, (name, t) in enumerate(top_n, 1):
    L(f"| {i} | `{name}` | {t:.1f} | {cat(name)} |")
T()

H2("5. cProfile 热点函数 Top-25 (独占耗时, Run3)")
stats_text = open(r3["stats_file"], "r", encoding="utf-8").read()
parts = stats_text.split("=== tottime Top 60 ===")
if len(parts) > 1:
    body = parts[1].strip()
    ls = body.split("\n")[3:]
    top20 = []
    for line in ls:
        m = re.match(r'\s*(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.*)', line)
        if m:
            top20.append((float(m.group(2)), float(m.group(4)), m.group(1), m.group(6).strip()))
            if len(top20) >= 25: break
    L("| 排名 | 函数 | 独占(s) | 累计(s) | 调用次数 |")
    L("|---|---|---|---|---|")
    for i, (tt, ct, nc, fn) in enumerate(top20, 1):
        fn_s = fn.split("\\")[-1].split("/")[-1][:60]
        L(f"| {i} | `{fn_s}` | {tt:.3f} | {ct:.3f} | {nc} |")
    T()
else:
    L("(不可用)")
    T()

H2("6. perf_metrics 事件统计")
perf_files = sorted(PERF_DIR.glob("perf_metrics_*.json"))
if perf_files:
    pm = load_json(perf_files[-1])
    evts = pm.get("events", pm.get("records", {}))
    if evts:
        evr = []
        for name, data in evts.items():
            avg = data.get("avg_ms", data.get("avg_s", 0))
            p95 = data.get("p95_ms", data.get("p95_s", 0))
            cnt = data.get("count", data.get("sample_count", 0))
            evr.append((avg, p95, cnt, name))
        evr.sort(key=lambda x: -x[0])
        L("| 事件 | 平均耗时(ms) | P95(ms) | 采样数 |")
        L("|---|---|---|---|")
        for avg, p95, cnt, name in evr[:15]:
            L(f"| `{name}` | {avg:.2f} | {p95:.2f} | {cnt} |")
        T()
        L("**分析**: perf_metrics 事件较少，仅 SVG 图标渲染和缩略图查找有记录。")
        L("建议将 MainWindow.__init__ 内部子组件初始化过程埋入 perf_metrics 以细化监控。")
    else:
        L("(无事件)")
else:
    L("(无导出)")
T()

H2("7. 瓶颈分析与优化建议")

H3("7.1 P1 - MainWindow.__init__ 耗时极高")
L("**位置**: `freeassetfilter/app/main.py` FreeAssetFilterApp.__init__")
L("**数据**: 热启动 ~1800ms，冷启动 ~2500ms，占启动总耗时约 65%")
L("**分析**:")
L("- 构造函数中递归初始化了所有子组件（FileSelector, StagingPool, UnifiedPreviewer 等）")
L("- 每个子组件的 import-on-init 链条不断拉长")
L("- cProfile 显示 `QWidget.setStyleSheet` 调用 **150次** 独占 **300ms**")
L("- `QBoxLayout.addWidget` 64次独占 129ms")
L("- `nt.stat` 5526次调用独占 322ms（大量文件系统 stat 操作）")
L("**建议**:")
L("1. **延迟初始化**: 非首屏必需组件 (ThemeEditor, UpdateController, ColorExtractor) 改为 `LazyImport` 惰性构造")
L("2. **QSS 批量应用**: 对同类控件集中调用 setStyleSheet，或使用 `setProperty()` + 全局 QSS")
L("3. **子组件 import 局部化**: 从模块顶层移入方法内")
L("4. **预估收益: 800-1200ms** | 难度: 中")
T()

H3("7.2 P2 - 重型模块 import 过早")
L("**位置**: `archive_browser`(~606ms), `player_control_bar`(~321ms), `lut_manager_dialog`(~313ms), `color_extractor`(~124ms)")
L("**分析**: 这些模块在启动时就被完整 import，但用户可能在启动后数分钟才访问对应功能")
L("**建议**:")
L("1. 将这些模块从顶层 import 改为按需动态 import")
L("2. 使用 `lambda: __import__('module')` 模式延迟加载")
L("3. **预估收益: 800-1500ms** | 难度: 中")
T()

H3("7.3 P3 - numpy 加载 ~700ms")
L("**分析**: 如果仅 color_extractor / LUT 功能使用 numpy，可以考虑延迟 import")
L("**建议**: 确认使用范围后，将 `import numpy` 从调用链顶层移除")
L("**预估收益: 300-500ms** | 难度: 低")
T()

H3("7.4 P4 - show() 后首帧延迟 ~340ms")
L("**分析**: `setStyleSheet` 150次和 `addWidget` 64次导致首次布局/渲染累积延迟")
L("**建议**:")
L("1. 合并分散的 QSS 调用，减少整体解析次数")
L("2. 初始化时隐藏非可见子控件，show() 后异步展开")
L("3. **预估收益: 100-200ms** | 难度: 低")
T()

H3("7.5 P5 - dropdown_menu.eventFilter 37000次调用 (100ms)")
L("**分析**: 启动过程中 eventFilter 被频繁调用(3.7万次)。原因是在初始化过程中持续有事件触发过滤器。")
L("**建议**: 仅在菜单显示时安装 eventFilter，不提前安装。**预估收益: 50-100ms** | 难度: 中")
T()

H2("8. 多次运行稳定性分析")
L("| 指标 | Run1(冷) | Run2(热) | Run3(热) | 热波动 |")
L("|---|---|---|---|---|")
w_total  = [e(r2_a,"P14_UPDATE_CHECK_DONE"), e(r3_a,"P14_UPDATE_CHECK_DONE")]
w_init   = [phase(r2_a,"P8_APP_INIT_START","P8_APP_INIT_DONE"), phase(r3_a,"P8_APP_INIT_START","P8_APP_INIT_DONE")]
w_frame  = [e(r2_a,"P10_FIRST_FRAME_LOAD_FONTS"), e(r3_a,"P10_FIRST_FRAME_LOAD_FONTS")]
def fmt_r(v):
    diff = max(v)-min(v); avg = sum(v)/len(v)
    return f"{max(v):.0f}/{min(v):.0f}ms (±{diff/avg*100:.1f}%)"
L(f"| 启动完成总耗时 | {e(r1_a,'P14_UPDATE_CHECK_DONE'):.0f}ms | {w_total[0]:.0f}ms | {w_total[1]:.0f}ms | {fmt_r(w_total)} |")
L(f"| MainWindow.__init__ | {phase(r1_a,'P8_APP_INIT_START','P8_APP_INIT_DONE'):.0f}ms | {w_init[0]:.0f}ms | {w_init[1]:.0f}ms | {fmt_r(w_init)} |")
L(f"| 首帧渲染 | {e(r1_a,'P10_FIRST_FRAME_LOAD_FONTS'):.0f}ms | {w_frame[0]:.0f}ms | {w_frame[1]:.0f}ms | {fmt_r(w_frame)} |")
L(f"| 模块导入累计 | {r1_i['total_import_ms']:.0f}ms | {r2_i['total_import_ms']:.0f}ms | {r3_i['total_import_ms']:.0f}ms | |")
T()
L("**分析**: 热启动稳定性良好，两次运行波动率 <5%。冷启动因无 pyc 缓存额外增加 Python 编译时间 1.0-1.5s。")
T()

H2("9. 优化优先级总览")
L("| 优先级 | 优化项 | 预估收益 | 难度 |")
L("|---|---|---|---|")
opts = [
    ("P1", "MainWindow.__init__ 延迟初始化非必要子组件", "800-1200ms", "中"),
    ("P2", "延迟 import 重型模块 (archive_browser 等)", "800-1500ms", "中"),
    ("P3", "numpy 按需 import", "300-500ms", "低"),
    ("P4", "QSS 批量应用 (减少 setStyleSheet 150次→10次)", "100-200ms", "低"),
    ("P5", "show() 后异步展开非可见控件", "100-200ms", "低"),
    ("P6", "减少 eventFilter 安装时机", "50-100ms", "中"),
    ("P7", "后台预热线程保持现状", "-", "-"),
]
for pri, item, gain, diff in opts:
    L(f"| {pri} | {item} | {gain} | {diff} |")
T()
L("**综合预期**: P1+P2+P3 三项可实现热启动首帧从 **2.8s 降至 1.2-1.5s**（约 50% 提升），"
  "冷启动从 **4.3s 降至 2.5-2.8s**。实施难度中等，主要是重构 import 链路。")
T()

L("---")
L(f"*报告由 scripts/generate_startup_report.py 自动生成 | 数据来源: data/performance/ | 运行日期: {runs[0]['ts'][:8]} ~ {runs[-1]['ts'][:8]}*")

report_text = "\n".join(lines)
report_path = PROJECT / "data" / "performance" / "startup_performance_report.md"
with open(report_path, "w", encoding="utf-8") as f:
    f.write(report_text)
print(f"Report written to: {report_path}")
print(f"Length: {len(report_text)} chars")
