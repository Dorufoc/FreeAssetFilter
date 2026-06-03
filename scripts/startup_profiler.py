#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# FreeAssetFilter Cold Start Profiler
# Entry: python scripts/startup_profiler.py

# Fix sys.path for project root
from __future__ import annotations
import sys; from pathlib import Path; _SCR = Path(__file__).resolve().parent.parent
if str(_SCR) not in sys.path: sys.path.insert(0, str(_SCR))
import os, sys, time, json, builtins, cProfile, argparse
from pathlib import Path
from datetime import datetime

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('FAF_PERF_METRICS_ENABLED', '1')
os.environ.setdefault('FAF_PERF_SAMPLE_LIMIT', '8192')

_script_start_ns = time.perf_counter_ns()

_import_times: dict[str, float] = {}
_import_call_order: list[str] = []
_original_import = builtins.__import__

def _timed_import(name, *args, **kwargs):
    t0 = time.perf_counter_ns()
    try:
        return _original_import(name, *args, **kwargs)
    finally:
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000
        top_name = name.split('.')[0]
        _import_times[top_name] = _import_times.get(top_name, 0.0) + elapsed_ms
        if top_name not in _import_call_order:
            _import_call_order.append(top_name)

builtins.__import__ = _timed_import

_anchors: dict[str, float] = {}
_anchor_meta: dict[str, str] = {}

def mark_anchor(name: str, *, desc: str = '') -> None:
    elapsed_ms = (time.perf_counter_ns() - _script_start_ns) / 1_000_000
    _anchors[name] = elapsed_ms
    if desc:
        _anchor_meta[name] = desc

mark_anchor('P_SCRIPT_START', desc='script start')
mark_anchor('P_PRE_IMPORT', desc='before main module import')

from freeassetfilter.app import main as faf_main
from freeassetfilter.utils.perf_metrics import export_perf_metrics

mark_anchor('P0_TOPLEVEL_IMPORTS_DONE', desc='main.py top-level imports done')

from PySide6.QtWidgets import QApplication

_orig_qapp_init = QApplication.__init__
def _patched_qapp_init(self, *args, **kwargs):
    mark_anchor('P5_QAPP_START', desc='QApplication.__init__ start')
    result = _orig_qapp_init(self, *args, **kwargs)
    mark_anchor('P5_QAPP_END', desc='QApplication.__init__ end')
    return result
QApplication.__init__ = _patched_qapp_init

_orig_main = faf_main.main
def _patched_main():
    mark_anchor('P3_MAIN_ENTRY', desc='main() entry')
    try:
        result = _orig_main()
        mark_anchor('P_PROFILE_MAIN_EXIT', desc='main() returned')
        return result
    except SystemExit:
        mark_anchor('P_PROFILE_MAIN_EXIT', desc='main() returned via SystemExit')
        raise
faf_main.main = _patched_main

_orig_app_init = faf_main.FreeAssetFilterApp.__init__
def _patched_app_init(self, *args, **kwargs):
    mark_anchor('P8_APP_INIT_START', desc='FreeAssetFilterApp.__init__ start')
    try:
        result = _orig_app_init(self, *args, **kwargs)
        mark_anchor('P8_APP_INIT_DONE', desc='FreeAssetFilterApp.__init__ done')
        return result
    except Exception:
        mark_anchor('P8_APP_INIT_FAILED')
        raise
faf_main.FreeAssetFilterApp.__init__ = _patched_app_init

_orig_schedule = faf_main.FreeAssetFilterApp.schedule_startup_tasks
_timer_fired = False
_profile_data_dir: str = ''
_run_timestamp: str = ''

def _patched_schedule(self):
    from PySide6.QtCore import QTimer
    mark_anchor('P9_SHOW_DONE_SCHEDULE_START', desc='show() returned, schedule_startup_tasks start')
    try:
        _orig_schedule(self)
    finally:
        mark_anchor('P9_SCHEDULE_DONE', desc='schedule_startup_tasks done')
        QTimer.singleShot(4000, lambda: _on_export_timer(self))

def _on_export_timer(main_window) -> None:
    global _timer_fired
    if _timer_fired:
        return
    _timer_fired = True
    mark_anchor('P15_EXPORT_TIMER_FIRED', desc='export timer fired')
    try:
        perf_path = export_perf_metrics()
        if perf_path:
            mark_anchor('P15_PERF_EXPORT_DONE', desc=f'perf_metrics exported: {Path(perf_path).name}')
    except Exception as e:
        _anchors['P15_PERF_EXPORT_ERROR'] = (time.perf_counter_ns() - _script_start_ns) / 1_000_000
        _anchor_meta['P15_PERF_EXPORT_ERROR'] = f'export failed: {e}'
    _save_anchor_data()
    _save_import_data()
    QApplication.quit()

faf_main.FreeAssetFilterApp.schedule_startup_tasks = _patched_schedule

_orig_load_fonts = faf_main.FreeAssetFilterApp._load_fonts_async
def _patched_load_fonts(self):
    mark_anchor('P10_FIRST_FRAME_LOAD_FONTS', desc='_load_fonts_async start (first frame rendered)')
    try:
        result = _orig_load_fonts(self)
        mark_anchor('P11_FONTS_DONE', desc='fonts async loaded')
        return result
    except Exception:
        mark_anchor('P11_FONTS_FAILED')
        raise
faf_main.FreeAssetFilterApp._load_fonts_async = _patched_load_fonts

_orig_check_backup = faf_main.FreeAssetFilterApp.check_and_restore_backup
def _patched_check_backup(self, *args, **kwargs):
    mark_anchor('P12_BACKUP_START', desc='backup restore start')
    try:
        result = _orig_check_backup(self, *args, **kwargs)
        mark_anchor('P12_BACKUP_DONE', desc='backup restore done')
        return result
    except Exception:
        mark_anchor('P12_BACKUP_FAILED')
        raise
faf_main.FreeAssetFilterApp.check_and_restore_backup = _patched_check_backup

_orig_warmup = faf_main.FreeAssetFilterApp._start_background_warmup
def _patched_warmup(self):
    mark_anchor('P13_WARMUP_START', desc='background warmup start')
    try:
        result = _orig_warmup(self)
        mark_anchor('P13_WARMUP_SCHEDULED', desc='warmup thread scheduled')
        return result
    except Exception:
        mark_anchor('P13_WARMUP_FAILED')
        raise
faf_main.FreeAssetFilterApp._start_background_warmup = _patched_warmup

_orig_warmup_thread_run = faf_main.StartupWarmupThread.run
def _patched_warmup_thread_run(self):
    mark_anchor('P13_WARMUP_THREAD_START', desc='StartupWarmupThread.run() start')
    try:
        result = _orig_warmup_thread_run(self)
        mark_anchor('P13_WARMUP_THREAD_DONE', desc='StartupWarmupThread.run() done')
        return result
    except Exception:
        mark_anchor('P13_WARMUP_THREAD_FAILED')
        raise
faf_main.StartupWarmupThread.run = _patched_warmup_thread_run

_orig_startup_flags = faf_main.FreeAssetFilterApp._try_start_update_check
def _patched_startup_flags(self):
    mark_anchor('P14_UPDATE_CHECK_ENTER', desc='_try_start_update_check triggered')
    result = _orig_startup_flags(self)
    mark_anchor('P14_UPDATE_CHECK_DONE', desc='all startup flags complete')
    return result
faf_main.FreeAssetFilterApp._try_start_update_check = _patched_startup_flags

def _save_anchor_data() -> None:
    ap = Path(_profile_data_dir) / f'startup_anchors_{_run_timestamp}.json'
    keys = list(_anchors.keys())
    phases = {}
    for i, k in enumerate(keys):
        pk = keys[i-1] if i > 0 else None
        pm = _anchors[k] - _anchors[pk] if pk and _anchors.get(pk) is not None else _anchors[k]
        phases[k] = {'elapsed_ms': round(_anchors[k], 3), 'phase_ms': round(pm, 3), 'desc': _anchor_meta.get(k, '')}
    with open(ap, 'w', encoding='utf-8') as f:
        json.dump({'script_start_ns': _script_start_ns, 'anchor_count': len(_anchors), 'phases': phases, 'raw_anchors_ms': {k: round(v, 3) for k, v in _anchors.items()}}, f, ensure_ascii=False, indent=2)
    print(f'  Anchors:   {ap.name}')

def _save_import_data() -> None:
    ip = Path(_profile_data_dir) / f'startup_imports_{_run_timestamp}.json'
    si = dict(sorted(_import_times.items(), key=lambda x: -x[1]))
    tim = sum(_import_times.values())
    with open(ip, 'w', encoding='utf-8') as f:
        json.dump({'total_import_ms': round(tim, 3), 'import_count': len(_import_times), 'imports': si, 'import_call_order': _import_call_order}, f, ensure_ascii=False, indent=2)
    print(f'  Imports:   {ip.name}')

def run_single_profile(output_dir: str) -> dict:
    global _profile_data_dir, _run_timestamp
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    _profile_data_dir = output_dir
    _run_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    _anchors.clear()
    _anchor_meta.clear()
    _anchors['P_SCRIPT_START'] = 0.0
    mark_anchor('P_PROFILER_START', desc='profiler launched')

    profiler = cProfile.Profile()
    profiler.enable()
    try:
        faf_main.main()
    except SystemExit:
        pass
    profiler.disable()
    mark_anchor('P_PROFILE_MAIN_RETURNED', desc='app.exec() returned')

    pp = os.path.join(output_dir, f'startup_profile_{_run_timestamp}.prof')
    profiler.dump_stats(pp)
    print(f'  Profile:   {Path(pp).name}')

    sp = os.path.join(output_dir, f'startup_stats_{_run_timestamp}.txt')
    with open(sp, 'w', encoding='utf-8') as f:
        import pstats
        ps = pstats.Stats(profiler, stream=f)
        f.write('=== cumtime Top 60 ===\n\n')
        ps.sort_stats('cumtime')
        ps.print_stats(60)
        f.write('\n\n=== tottime Top 60 ===\n\n')
        ps.sort_stats('tottime')
        ps.print_stats(60)
        f.write('\n\n=== ncalls Top 30 ===\n\n')
        ps.sort_stats('ncalls')
        ps.print_stats(30)
    print(f'  Stats:     {Path(sp).name}')

    tim = sum(_import_times.values())
    meta = {
        'timestamp': _run_timestamp, 'python_version': sys.version,
        'platform': sys.platform, 'offscreen': True,
        'qt_qpa_platform': os.environ.get('QT_QPA_PLATFORM', ''),
        'total_wall_time_ms': round(_anchors.get('P_PROFILE_MAIN_EXIT', 0), 3),
        'anchor_count': len(_anchors), 'import_count': len(_import_times),
        'import_total_ms': round(tim, 3),
    }
    mp = os.path.join(output_dir, f'startup_meta_{_run_timestamp}.json')
    with open(mp, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f'  Meta:      {Path(mp).name}')
    return {'profile': pp, 'stats': sp, 'meta': mp}

def main() -> None:
    parser = argparse.ArgumentParser(description='FreeAssetFilter cold start profiler')
    parser.add_argument('--output-dir', default='', help='output dir (default: data/performance/)')
    args, remaining = parser.parse_known_args()
    # Clean sys.argv for the main app
    sys.argv = [sys.argv[0]] + remaining
    if args.output_dir:
        out_dir = args.output_dir
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out_dir = os.path.join(base, 'data', 'performance')
    print('=' * 55)
    print('  FreeAssetFilter Cold Start Profiler')
    print(f'  Output: {out_dir}')
    print('=' * 55)
    run_single_profile(out_dir)
    tot = _anchors.get('P_PROFILE_MAIN_EXIT', 0)
    print(f'  Total:    {tot:.1f} ms ({tot/1000:.2f} s)')

if __name__ == '__main__':
    main()
