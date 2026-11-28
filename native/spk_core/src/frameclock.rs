//! `frameclock.rs` —— vsync 相位对齐的帧时钟（R7/P4：Rust 帧调度器）。
//!
//! ## 为什么需要它
//!
//! Python 侧的 `FrameScheduler`（`core/managers/frame_scheduler.py`）用
//! `QTimer(PreciseTimer)` 按面板帧间隔自由跑（240Hz → 4ms）。定时器与显示器的
//! vblank **相位无关**：两者周期只要差一点点就会周期性"拍频"，表现为偶发重复
//! 或丢帧（微抖动，实测 240Hz 下相漂可达数毫秒）。要真正稳定，每一帧必须由
//! **一个显示刷新事件**唤醒，而不是由固定间隔的定时器猜。
//!
//! ## 做法
//!
//! - **相位锚点**：`DwmFlush()` 阻塞到下一次桌面合成返回，返回时刻就是一个
//!   vblank 锚点（本机实测 240Hz 面板 240.5 次/秒、间隔中位 4.15ms）。每帧调用
//!   一次即"锁相"：帧率天然等于面板刷新率，不会拍频。
//! - **低帧率仍对齐**：目标帧率低于面板时（空闲档 30Hz），不是自由等 33ms，
//!   而是用高精度可等待定时器先睡 `(k-1)` 个合成周期，再用一次 `DwmFlush()`
//!   精确落在第 k 个合成上（`k = round(目标周期 / 合成周期)`）。这样既省电
//!   （每秒只醒 k 次）又不抖动（每次都对齐同一条 vblank）。
//! - **无合成时兜底**：`DwmFlush()` 失败（DWM 关闭 / 远程会话）或拿不到高精度
//!   定时器时，自动切到按目标间隔等待，并在 `stats` 里以 `timer_frames` 标出。
//! - **自校准**：用实测的帧间隔反推面板周期（`interval / divisor`，EMA 平滑），
//!   只在偏差 >6% 时采纳，并据此重算除数——面板刷新率被系统改掉（例如切到
//!   60Hz 电池模式）后不需要重启应用。
//!
//! ## 调用契约（Python 侧）
//!
//! 句柄由**一个专用线程**持有：该线程循环 `spk_frameclock_wait()`，返回后把
//! "该出帧了"投递给 GUI 线程。`wait` 内部是内核等待，**不占 CPU、不持 GIL**
//! （ctypes 调用期间释放 GIL）。
//!
//! - `spk_frameclock_create(hz)` → 非零句柄；`0` 表示失败（调用方回退 QTimer）。
//! - `spk_frameclock_wait(handle, timeout_ms)` → 正数 = 已出帧序号；
//!   `-1` 非法入参、`-2` 非法句柄、`-3` 超时（本帧无 vblank，调用方照常出帧）、
//!   `-4` 已停止（`stop` 后正常退出）。
//! - `spk_frameclock_stop()` 置停止标志，阻塞中的 `wait` 最多在**一个合成周期**
//!   内返回 `-4`；`spk_frameclock_resume()` 清除标志以便再次启动。
//! - `spk_frameclock_free()` 只从注册表摘除；在途 `wait` 持有 `Arc`，不会悬垂。
//!   调用方必须先 `stop` 并等线程退出，再 `free`。
//!
//! 所有导出都在 `catch_unwind` 兜底内，绝不 panic 跨 FFI。

use std::collections::HashMap;
use std::ffi::{c_char, c_void};
use std::os::raw::{c_double, c_int};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicBool, AtomicI64, AtomicU32, AtomicU64, Ordering};
use std::sync::{Arc, LazyLock, Mutex};

use crate::{STATUS_INVALID_ARG, STATUS_OK, alloc_json_message, catch_to_ptr, catch_to_status};

// ---------------------------------------------------------------------------
// 状态码（本模块局部语义，与 crate 通用码分开命名以免混淆）
// ---------------------------------------------------------------------------

/// 非法句柄（`0` / 未知 / 已 free）。
const STATUS_INVALID_HANDLE: i32 = -2;
/// 等待超时：本帧没有等到 vblank（调用方仍应出帧，避免动画停摆）。
const STATUS_TIMEOUT: i32 = -3;
/// 时钟已停止（正常退出路径）。
const STATUS_STOPPED: i32 = -4;
/// 内部错误（定时器不可用等）。
const STATUS_CLOCK_FAILED: i32 = -5;

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------

/// 目标帧率下限（Hz）。
const MIN_TARGET_HZ: f64 = 1.0;
/// 目标帧率上限（Hz），防止误传把定时器压到 1ms 以下。
const MAX_TARGET_HZ: f64 = 1000.0;
/// 单帧最短周期（1ms）。
const MIN_PERIOD_NS: i64 = 1_000_000;
/// 同时存在的时钟句柄上限（正常只有 1 个）。
const MAX_HANDLES: usize = 8;
/// 间隔统计环形缓冲长度。
const WINDOW: usize = 256;
/// 无面板周期信息时的默认值（60Hz）。
const DEFAULT_PANEL_HZ: f64 = 60.0;
/// 除数上限（30Hz 目标 / 240Hz 面板 = 8）。
const MAX_DIVISOR: u32 = 16;
/// 实测周期的 EMA 权重。
const PERIOD_EMA_ALPHA: f64 = 0.2;
/// 实测周期与目标偏离超过该比例才采纳（防止把抖动算进周期）。
const PERIOD_ACCEPT_RATIO: f64 = 0.06;
/// 锁相环用的平滑周期权重（比面板周期估计更重，追求平稳而非快速收敛）。
const PERIOD_PLL_ALPHA: f64 = 0.08;
/// 锁相环相位纠偏系数：每次观测只把预测网格往实测值拉一小步，
/// 避免单帧抖动被整帧放大成跳帧。
const PHASE_GAIN: f64 = 0.15;
/// 每隔多少帧用一次 `DwmFlush` 重新锚定相位网格（其余帧只走高精度睡眠）。
/// 预热帧数：不足这么多帧时不做锁相（还没有可靠的周期/相位估计）。
const WARMUP_FRAMES: u64 = 6;
/// 换档后跳过的采样帧数（切档那一拍的间隔不具代表性）。
const SETTLE_FRAMES: u32 = 3;

// ---------------------------------------------------------------------------
// Win32 FFI
// ---------------------------------------------------------------------------

#[link(name = "dwmapi")]
extern "system" {
    /// 阻塞到下一次桌面合成完成；`S_OK`(0) 表示成功。
    fn DwmFlush() -> i32;
    /// 桌面合成（DWM）是否启用；`0` 表示成功。
    fn DwmIsCompositionEnabled(enabled: *mut i32) -> i32;
}

#[link(name = "kernel32")]
extern "system" {
    fn QueryPerformanceCounter(counter: *mut i64) -> i32;
    fn QueryPerformanceFrequency(freq: *mut i64) -> i32;
    fn CreateWaitableTimerExW(
        attrs: *mut c_void,
        name: *const u16,
        flags: u32,
        access: u32,
    ) -> *mut c_void;
    fn SetWaitableTimer(
        timer: *mut c_void,
        due_ns: *const i64,
        period_ms: i32,
        completion: *mut c_void,
        arg: *mut c_void,
        resume: i32,
    ) -> i32;
    fn WaitForSingleObject(handle: *mut c_void, ms: u32) -> u32;
    fn CloseHandle(handle: *mut c_void) -> i32;
}

/// `CreateWaitableTimerExW` 的 `CREATE_WAITABLE_TIMER_HIGH_RESOLUTION`
///（Win10 1803+；不可用时退化为 1ms 精度的普通定时器）。
const CREATE_WAITABLE_TIMER_HIGH_RESOLUTION: u32 = 0x0000_0002;
/// `TIMER_ALL_ACCESS`。
const TIMER_ALL_ACCESS: u32 = 0x001F_0003;
/// `WAIT_FOR_SINGLE_OBJECT` 的无限等待。
const INFINITE: u32 = 0xFFFF_FFFF;

// ---------------------------------------------------------------------------
// 时间基准（QPC → 纳秒）
// ---------------------------------------------------------------------------

/// QPC 频率缓存（`0` 表示尚未读取）。
static QPC_FREQ: AtomicI64 = AtomicI64::new(0);

/// 读取 QPC 频率（失败时退回 1MHz，保证不除零）。
fn qpc_freq() -> i64 {
    let cached = QPC_FREQ.load(Ordering::Relaxed);
    if cached > 0 {
        return cached;
    }
    let mut freq: i64 = 0;
    // SAFETY：写入本地栈变量，指针有效。
    let ok = unsafe { QueryPerformanceFrequency(&mut freq) };
    if ok == 0 || freq <= 0 {
        return 1_000_000;
    }
    QPC_FREQ.store(freq, Ordering::Relaxed);
    freq
}

/// 当前单调时间（纳秒）。用 `i128` 中间量避免 `counter * 1e9` 溢出。
fn now_ns() -> i64 {
    let mut counter: i64 = 0;
    // SAFETY：写入本地栈变量，指针有效。
    let ok = unsafe { QueryPerformanceCounter(&mut counter) };
    if ok == 0 {
        return 0;
    }
    let ns = (i128::from(counter)) * 1_000_000_000i128 / i128::from(qpc_freq());
    ns as i64
}

// ---------------------------------------------------------------------------
// 可等待定时器
// ---------------------------------------------------------------------------

/// 可等待定时器句柄（原始指针需手动声明 `Send`/`Sync` 才能放进 `Mutex`）。
struct TimerHandle(*mut c_void);

// SAFETY：句柄只在 `Clock` 内部通过 `SetWaitableTimer`/`WaitForSingleObject`
// 使用，且 `Clock` 由 `Arc` 共享；内核对象本身线程安全。
unsafe impl Send for TimerHandle {}
unsafe impl Sync for TimerHandle {}

impl Drop for TimerHandle {
    fn drop(&mut self) {
        if !self.0.is_null() {
            // SAFETY：句柄来自 CreateWaitableTimerExW，且只在这里关闭一次。
            unsafe {
                let _ = CloseHandle(self.0);
            }
        }
    }
}

/// 创建高精度可等待定时器；高精度标志不支持时退回普通定时器。
fn create_timer() -> TimerHandle {
    // SAFETY：attrs/name 传 null 表示默认安全属性、匿名定时器。
    let high = unsafe {
        CreateWaitableTimerExW(
            std::ptr::null_mut(),
            std::ptr::null(),
            CREATE_WAITABLE_TIMER_HIGH_RESOLUTION,
            TIMER_ALL_ACCESS,
        )
    };
    if !high.is_null() {
        return TimerHandle(high);
    }
    // SAFETY：同上，flags=0 走 1ms 精度定时器。
    let plain = unsafe {
        CreateWaitableTimerExW(
            std::ptr::null_mut(),
            std::ptr::null(),
            0,
            TIMER_ALL_ACCESS,
        )
    };
    TimerHandle(plain)
}

// ---------------------------------------------------------------------------
// 时钟状态
// ---------------------------------------------------------------------------

/// 当前出帧时钟来源。
#[derive(Clone, Copy, PartialEq, Eq)]
enum Mode {
    /// 由 `DwmFlush` 的合成事件驱动（相位对齐）。
    Vsync,
    /// 由高精度定时器按目标间隔驱动（无合成时的兜底）。
    Timer,
}

impl Mode {
    /// JSON/日志用的名字。
    fn as_str(self) -> &'static str {
        match self {
            Mode::Vsync => "vsync",
            Mode::Timer => "timer",
        }
    }
}

/// 受 `Mutex` 保护的时钟内部状态（只在非阻塞的短临界区里访问）。
struct ClockState {
    timer: TimerHandle,
    mode: Mode,
    /// 实测合成周期（纳秒），用于计算除数与分段睡眠。
    panel_period_ns: i64,
    /// 创建时 `DwmFlush` 探测到的周期：给它 ±5% 的容差当锚点，防止估计值
    /// 被偶发的偏长间隔一点点带跑（实测会从 240Hz 缓慢漂到 211Hz）。
    probe_period_ns: i64,
    /// 锁相环用的平滑出帧周期（纳秒）。
    period_est_ns: i64,
    /// 锁相环预测的下一帧出帧时刻（纳秒；0 表示尚未锁定）。
    phase_ns: i64,
    /// 最近一次相位误差（纳秒，正数表示比预测晚）。
    phase_error_ns: i64,
    /// 重锚次数与"迟到"次数（诊断用）。
    resyncs: u64,
    late: u64,
    /// 换档后还需跳过的采样帧数。
    settle: u32,
    /// `DwmFlush()` 从调用到返回的延迟（纳秒，EMA）。返回时刻是"合成完成后"，
    /// 比真实 vblank 晚这段延迟；低频档以它为锚点修正，否则会整整晚一帧
    /// （实测 30Hz 档从 33.2ms 变成 37.5ms）。
    flush_latency_ns: i64,
    /// 上一帧出帧时刻（纳秒）。
    last_emit_ns: i64,
    /// 在这之前不再调用 `DwmFlush`（纳秒，0 表示可用）。
    ///
    /// `DwmFlush()` 没有超时参数：桌面静止时 DWM 可能长时间不合成，调用会
    /// 一直阻塞（实测单次 200ms+、3 秒内 30+ 次），把整个时钟泵卡死。一旦
    /// 观测到一次"慢 flush"，就停用 flush 一秒，改用高精度睡眠按相位推进，
    /// 之后再试探。
    flush_blocked_until_ns: i64,
    /// 慢 flush 次数（诊断）。
    slow_flushes: u64,
    /// 累计出帧数。
    frames: u64,
    /// 其中由定时器兜底出的帧数。
    timer_frames: u64,
    /// 超时次数。
    timeouts: u64,
    /// 间隔环形缓冲与写指针。
    intervals: [i64; WINDOW],
    written: usize,
    /// 总样本数（用于算 p95 的 rank）。
    total: u64,
}

/// 一个帧时钟实例。
pub(crate) struct Clock {
    /// 目标帧周期（纳秒）。
    target_period_ns: AtomicI64,
    /// 相对面板合成的除数（1 = 每个合成出帧）。
    divisor: AtomicU32,
    /// 停止标志（`stop` 置位、`resume` 清除）。
    stop: AtomicBool,
    /// 已出帧序号。
    seq: AtomicU64,
    state: Mutex<ClockState>,
}

impl Clock {
    /// 新建时钟并按目标帧率初始化。
    ///
    /// 这里**不做** vblank 探测：探测要连着调 9 次 `DwmFlush`，桌面静止时每次
    /// 都可能阻塞到下一次合成（实测在真实窗口启动阶段能卡主线程几十到上百
    /// 毫秒）。初始面板周期先按目标帧率取，前几帧的 flush 间隔会把它校准到
    /// 真实刷新率。
    fn new(hz: f64) -> Self {
        let panel_period = period_ns_from_hz(hz).clamp(MIN_PERIOD_NS, 1_000_000_000);
        let clock = Clock {
            target_period_ns: AtomicI64::new(period_ns_from_hz(hz)),
            divisor: AtomicU32::new(1),
            stop: AtomicBool::new(false),
            seq: AtomicU64::new(0),
            state: Mutex::new(ClockState {
                timer: create_timer(),
                mode: Mode::Vsync,
                panel_period_ns: panel_period,
                probe_period_ns: 0,
                period_est_ns: panel_period,
                phase_ns: 0,
                phase_error_ns: 0,
                resyncs: 0,
                late: 0,
                settle: SETTLE_FRAMES,
                flush_latency_ns: 0,
                last_emit_ns: 0,
                flush_blocked_until_ns: 0,
                slow_flushes: 0,
                frames: 0,
                timer_frames: 0,
                timeouts: 0,
                intervals: [0; WINDOW],
                written: 0,
                total: 0,
            }),
        };
        clock.recompute_divisor();
        clock
    }

    /// 设置目标帧率（幂等、可随时调用，不打断在途 `wait`）。
    ///
    /// 换档会清空相位网格并跳过后几帧的周期采样：切档那一拍的间隔既不是旧档
    /// 也不是新档的周期，若被当作样本会把面板周期估计带偏（曾把 240Hz 估成
    /// 262.8Hz、把 30Hz 的除数算成 9）。
    fn set_rate(&self, hz: f64) {
        self.target_period_ns
            .store(period_ns_from_hz(hz), Ordering::Release);
        if let Ok(mut guard) = self.state.lock() {
            guard.phase_ns = 0;
            guard.phase_error_ns = 0;
            guard.settle = SETTLE_FRAMES;
        }
        self.recompute_divisor();
    }

    /// 依据实测面板周期重算除数（目标 30Hz / 面板 240Hz → 8）。
    fn recompute_divisor(&self) {
        let panel = self
            .state
            .lock()
            .map(|g| g.panel_period_ns)
            .unwrap_or(0)
            .max(1);
        let target = self.target_period_ns.load(Ordering::Acquire).max(MIN_PERIOD_NS);
        let ratio = (target as f64) / (panel as f64);
        let divisor = if ratio.is_finite() {
            (ratio.round().max(1.0) as u32).clamp(1, MAX_DIVISOR)
        } else {
            1
        };
        self.divisor.store(divisor, Ordering::Release);
    }

    /// 停止信号是否已置位。
    fn is_stopped(&self) -> bool {
        self.stop.load(Ordering::Acquire)
    }

    /// 定时器原始句柄（不持锁返回，供分段睡眠使用）。
    fn timer_ptr(&self) -> *mut c_void {
        self.state
            .lock()
            .map(|g| g.timer.0)
            .unwrap_or(std::ptr::null_mut())
    }

    /// 相对睡眠 `ns` 纳秒；定时器不可用返回 `false`。
    fn sleep_ns(&self, ns: i64) -> bool {
        if ns <= 0 {
            return true;
        }
        let timer = self.timer_ptr();
        if timer.is_null() {
            return false;
        }
        // 相对 due time 用负的 100ns 单位；最少 1 个单位避免 0 表示"绝对时间"。
        let due = -((ns / 100).max(1));
        // SAFETY：timer 句柄有效（Clock 未释放），参数均为合法指针/标量。
        let ok = unsafe {
            SetWaitableTimer(
                timer,
                &due,
                0,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                0,
            )
        };
        if ok == 0 {
            return false;
        }
        // SAFETY：等待同一个有效句柄；无限等待由定时器到期唤醒。
        unsafe {
            let _ = WaitForSingleObject(timer, INFINITE);
        }
        true
    }

    /// 读取当前模式快照。
    fn mode(&self) -> Mode {
        self.state
            .lock()
            .map(|g| g.mode)
            .unwrap_or(Mode::Timer)
    }

    /// 切到定时器兜底模式（只会发生一次，之后不再尝试 vblank）。
    fn downgrade_to_timer(&self) {
        if let Ok(mut guard) = self.state.lock() {
            guard.mode = Mode::Timer;
        }
    }

    /// 记录一帧并返回序号。
    ///
    /// 面板周期只从 **全速帧**（`divisor == 1`）的间隔里估计：低频档的间隔是
    /// `divisor × 面板周期`，一旦除数算错就会自我强化（30Hz 档曾把除数从 8
    /// 抬到 9、把面板估成 262.8Hz）。锁相环的相位网格同样只在全速档推进。
    ///
    /// Args:
    ///     at_ns: 本帧出帧时刻（QPC 纳秒）。
    ///     anchored: 本帧是否由 `DwmFlush` 重锚（否则只走了高精度睡眠）。
    fn record_frame(&self, at_ns: i64, anchored: bool) -> u64 {
        let seq = self.seq.fetch_add(1, Ordering::AcqRel) + 1;
        let divisor = self.divisor.load(Ordering::Acquire).max(1) as i64;
        let target = self.target_period_ns.load(Ordering::Acquire);
        let mut need_divisor_recalc = false;
        if let Ok(mut guard) = self.state.lock() {
            if guard.settle > 0 {
                guard.settle -= 1;
                // 换档后的第一拍只更新时间戳，不采样、不推进相位。
                guard.last_emit_ns = at_ns;
                guard.frames = guard.frames.saturating_add(1);
                return seq;
            }
            if guard.last_emit_ns > 0 && at_ns > guard.last_emit_ns {
                let interval = at_ns - guard.last_emit_ns;
                let slot = guard.written % WINDOW;
                guard.intervals[slot] = interval;
                guard.written = guard.written.wrapping_add(1);
                guard.total = guard.total.saturating_add(1);
                if divisor == 1 {
                    // 只把"准时"的间隔当周期样本：迟到帧（>1.4 倍）和被阻塞的
                    // 间隔会让面板估计一路走低（曾从 240Hz 漂到 207Hz）。
                    let est_before = if guard.period_est_ns > 0 {
                        guard.period_est_ns
                    } else {
                        guard.panel_period_ns.max(MIN_PERIOD_NS)
                    };
                    let on_time = interval as f64 <= est_before as f64 * 1.4;
                    if on_time {
                        // 全速帧的间隔就是面板周期本身。
                        let implied = interval as f64;
                        let current = guard.panel_period_ns as f64;
                        if current > 0.0
                            && implied > current * 0.5
                            && implied < current * 2.0
                            && (implied - current).abs() / current > PERIOD_ACCEPT_RATIO
                        {
                            let blended = (current * (1.0 - PERIOD_EMA_ALPHA)
                                + implied * PERIOD_EMA_ALPHA)
                                .round() as i64;
                            // 面板频率不会自己变：把估计值夹在"锁定后的基准"±5%
                            // 内，否则连续偏长的样本会让它缓慢爬升（周期变长）。
                            // 基准在头几十帧稳定后才取（创建时不做探测）。
                            if guard.probe_period_ns == 0 && guard.total >= 30 {
                                guard.probe_period_ns = guard.panel_period_ns;
                            }
                            if guard.probe_period_ns > 0 {
                                let anchor = guard.probe_period_ns.max(MIN_PERIOD_NS);
                                let lo = (anchor as f64 * 0.95).round() as i64;
                                let hi = (anchor as f64 * 1.05).round() as i64;
                                guard.panel_period_ns = blended.clamp(lo, hi);
                            } else {
                                guard.panel_period_ns = blended.max(MIN_PERIOD_NS);
                            }
                            need_divisor_recalc = true;
                        }
                        // 锁相环周期：只吸收接近当前估计的样本，避免把一次掉帧
                        // 当成"面板变慢"。
                        let est = guard.period_est_ns as f64;
                        if est > 0.0 && implied > est * 0.9 && implied < est * 1.1 {
                            guard.period_est_ns = (est * (1.0 - PERIOD_PLL_ALPHA)
                                + implied * PERIOD_PLL_ALPHA)
                                .round() as i64;
                        } else if est <= 0.0 {
                            guard.period_est_ns = interval;
                        }
                    }
                }
                // 间隔明显超过目标（>1.5 倍）记一次轻微"迟到"，供诊断。
                if target > 0 && interval > target * 3 / 2 {
                    guard.timeouts = guard.timeouts.saturating_add(1);
                }
            }
            guard.last_emit_ns = at_ns;
            guard.frames = guard.frames.saturating_add(1);

            // 锁相环：推进预测网格，并用观测误差缓慢纠偏。
            let period = if guard.period_est_ns > 0 {
                guard.period_est_ns
            } else {
                guard.panel_period_ns.max(MIN_PERIOD_NS)
            };
            if divisor == 1 {
                let expected = guard.phase_ns;
                if expected > 0 {
                    let error = at_ns - expected;
                    guard.phase_error_ns = error;
                    let gain = if anchored { PHASE_GAIN } else { PHASE_GAIN * 0.5 };
                    let correction = (error as f64 * gain).round() as i64;
                    guard.phase_ns = expected + period + correction;
                    if error > period / 2 {
                        guard.late = guard.late.saturating_add(1);
                    }
                } else {
                    guard.phase_ns = at_ns + period;
                }
            } else {
                // 低频档不做相位网格：每帧都由 DwmFlush 重新锚定。
                guard.phase_ns = 0;
                guard.phase_error_ns = 0;
            }
        }
        if need_divisor_recalc {
            self.recompute_divisor();
        }
        seq
    }

    /// 锁相环快照：`(面板周期, 预测相位, 已出帧数, 换档剩余帧, 上一帧时刻)`。
    fn pll_snapshot(&self) -> (i64, i64, u64, u32, i64) {
        match self.state.lock() {
            Ok(guard) => (
                guard.panel_period_ns,
                guard.phase_ns,
                guard.frames,
                guard.settle,
                guard.last_emit_ns,
            ),
            Err(_) => (0, 0, 0, 0, 0),
        }
    }

    /// 调用一次 `DwmFlush()` 并返回**估计的真实 vblank 时刻**。
    ///
    /// `DwmFlush` 在合成完成后才返回，所以返回时刻比 vblank 晚一段延迟（实测
    /// 约 1ms）。直接用返回时刻当锚点会让低频档的目标落在目标 vblank 之后，
    /// 于是整整晚一帧（30Hz 实测 37.5ms 而非 33.2ms），因此这里减去观测到的
    /// 延迟（EMA）。以 vblank 域记账也顺带把 flush 延迟抖动挡在间隔样本之外。
    ///
    /// Returns:
    ///     `Some(vblank_ns)`；`None` 表示 DWM 不可用（调用方应切定时器兜底）。
    fn flush_vblank(&self) -> Option<i64> {
        let before = now_ns();
        // SAFETY：无参数、无副作用，只是等待下一次合成。
        let hr = unsafe { DwmFlush() };
        let at = now_ns();
        if hr != 0 {
            return None;
        }
        let latency = (at - before).max(0);
        let mut anchor = at;
        if let Ok(mut guard) = self.state.lock() {
            let panel = guard.panel_period_ns.max(MIN_PERIOD_NS);
            // 慢 flush 熔断：DwmFlush 没有超时参数，桌面静止时 DWM 可能长时间
            // 不合成（实测单次 200ms+），把它当节拍源会把整个时钟泵卡死。
            // 一次明显超长就关掉 flush 一秒，改用高精度睡眠按相位推进。
            if latency > panel * 3 {
                guard.flush_blocked_until_ns = at + 1_000_000_000;
                guard.slow_flushes = guard.slow_flushes.saturating_add(1);
                return None;
            }
            let prior = if guard.flush_latency_ns > 0 {
                guard.flush_latency_ns
            } else {
                panel / 4
            };
            if latency > 0 && latency <= panel * 2 {
                guard.flush_latency_ns = if guard.flush_latency_ns > 0 {
                    (guard.flush_latency_ns as f64 * (1.0 - PERIOD_EMA_ALPHA)
                        + latency as f64 * PERIOD_EMA_ALPHA)
                        .round() as i64
                } else {
                    latency
                };
            }
            anchor = (at - prior).max(before);
        }
        Some(anchor)
    }

    /// `DwmFlush` 当前是否被熔断（改为纯睡眠推进）。
    fn flush_blocked(&self) -> bool {
        match self.state.lock() {
            Ok(guard) => {
                guard.flush_blocked_until_ns > 0 && now_ns() < guard.flush_blocked_until_ns
            }
            Err(_) => false,
        }
    }

    /// 记一次"无睡眠余量、纯 DwmFlush 轮询"的帧（相位预测没赶上）。
    fn note_resync(&self) {
        if let Ok(mut guard) = self.state.lock() {
            guard.resyncs = guard.resyncs.saturating_add(1);
        }
    }

    /// 记录一次定时器兜底帧。
    fn note_timer_frame(&self) {
        if let Ok(mut guard) = self.state.lock() {
            guard.timer_frames = guard.timer_frames.saturating_add(1);
        }
    }

    /// 记一次显式超时。
    fn note_timeout(&self) {
        if let Ok(mut guard) = self.state.lock() {
            guard.timeouts = guard.timeouts.saturating_add(1);
        }
    }

    /// 阻塞到下一帧（`Ok(序号)`）或错误码。
    ///
    /// `timeout_ns <= 0` 表示无限等待。
    fn wait_next(&self, timeout_ns: i64) -> Result<u64, i32> {
        let start = now_ns();
        let deadline = if timeout_ns > 0 {
            start.saturating_add(timeout_ns)
        } else {
            i64::MAX
        };
        loop {
            if self.is_stopped() {
                return Err(STATUS_STOPPED);
            }
            if now_ns() > deadline {
                self.note_timeout();
                return Err(STATUS_TIMEOUT);
            }
            match self.mode() {
                Mode::Vsync => {
                    let divisor = i64::from(self.divisor.load(Ordering::Acquire)).max(1);
                    let (panel, phase, frames, settle, last_emit) = self.pll_snapshot();
                    let panel = panel.max(MIN_PERIOD_NS);

                    if divisor > 1 {
                        // 低频档：以「上一帧 + divisor × 面板周期」为锚点睡到目标
                        // 前 1/4 帧，再用一次 DwmFlush 落到那条 vblank 上。锚点法
                        // 让误差不累积（旧实现按 `panel × (divisor-1)` 睡，短一点
                        // 少一点都会逐帧漂）。
                        let anchor = if last_emit > 0 { last_emit } else { now_ns() };
                        let target = anchor.saturating_add(panel.saturating_mul(divisor));
                        let sleep = target
                            .saturating_sub(panel / 4)
                            .saturating_sub(now_ns())
                            .max(0);
                        if !self.sleep_ns(sleep) {
                            self.downgrade_to_timer();
                            continue;
                        }
                        if self.is_stopped() {
                            return Err(STATUS_STOPPED);
                        }
                        if self.flush_blocked() {
                            let remain = target.saturating_sub(now_ns()).max(0);
                            if !self.sleep_ns(remain) {
                                return Err(STATUS_CLOCK_FAILED);
                            }
                            if self.is_stopped() {
                                return Err(STATUS_STOPPED);
                            }
                            let at = now_ns();
                            if at > deadline {
                                self.note_timeout();
                                return Err(STATUS_TIMEOUT);
                            }
                            return Ok(self.record_frame(at, false));
                        }
                        let at = match self.flush_vblank() {
                            Some(v) => v,
                            None => {
                                if self.flush_blocked() {
                                    continue;
                                }
                                self.downgrade_to_timer();
                                continue;
                            }
                        };
                        if at > deadline {
                            self.note_timeout();
                            return Err(STATUS_TIMEOUT);
                        }
                        return Ok(self.record_frame(at, true));
                    }

                    // 全速档：每一帧都用 DwmFlush 锚定（丢锚就会整整晚一帧——
                    // 实测「醒晚了再 DwmFlush」把 p95 从 4.9ms 推到 7.1ms）。
                    // 锁相环只用来**省唤醒**：相位还有充足余量时先睡掉大半段，
                    // 剩下的交给 DwmFlush 精确落点，所以永远不会因为睡眠误差丢帧。
                    let locked = settle == 0 && frames >= WARMUP_FRAMES && phase > 0;
                    if locked {
                        let remaining = phase.saturating_sub(now_ns());
                        let trim = remaining.saturating_sub(panel / 2);
                        if trim > panel / 4 && !self.sleep_ns(trim) {
                            self.downgrade_to_timer();
                            continue;
                        }
                        if self.is_stopped() {
                            return Err(STATUS_STOPPED);
                        }
                        if trim <= panel / 4 {
                            // 余量不足，这一帧只能纯 DwmFlush 轮询（记数仅供参考）。
                            self.note_resync();
                        }
                    }
                    if self.flush_blocked() {
                        // 熔断期：不碰 DwmFlush，纯高精度睡眠按相位推进。
                        let target = if phase > 0 { phase } else { now_ns().saturating_add(panel) };
                        let remain = target.saturating_sub(now_ns()).max(0);
                        if !self.sleep_ns(remain) {
                            return Err(STATUS_CLOCK_FAILED);
                        }
                        if self.is_stopped() {
                            return Err(STATUS_STOPPED);
                        }
                        let at = now_ns();
                        if at > deadline {
                            self.note_timeout();
                            return Err(STATUS_TIMEOUT);
                        }
                        return Ok(self.record_frame(at, false));
                    }
                    let at = match self.flush_vblank() {
                        Some(v) => v,
                        None => {
                            if self.flush_blocked() {
                                // 慢 flush 已熔断：回到本循环开头走纯睡眠路径。
                                continue;
                            }
                            // DWM 不可用（远程会话/合成关闭）→ 之后走定时器。
                            self.downgrade_to_timer();
                            continue;
                        }
                    };
                    if at > deadline {
                        self.note_timeout();
                        return Err(STATUS_TIMEOUT);
                    }
                    return Ok(self.record_frame(at, true));
                }
                Mode::Timer => {
                    let target = self.target_period_ns.load(Ordering::Acquire).max(MIN_PERIOD_NS);
                    if !self.sleep_ns(target) {
                        return Err(STATUS_CLOCK_FAILED);
                    }
                    let at = now_ns();
                    if self.is_stopped() {
                        return Err(STATUS_STOPPED);
                    }
                    if at > deadline {
                        self.note_timeout();
                        return Err(STATUS_TIMEOUT);
                    }
                    self.note_timer_frame();
                    return Ok(self.record_frame(at, true));
                }
            }
        }
    }

    /// 统计快照（JSON）。
    fn stats_json(&self, handle: u64) -> serde_json::Value {
        let target_hz = 1e9 / (self.target_period_ns.load(Ordering::Acquire).max(MIN_PERIOD_NS) as f64);
        let divisor = self.divisor.load(Ordering::Acquire).max(1);
        let (
            mode,
            panel_period,
            frames,
            timer_frames,
            timeouts,
            p50,
            p95,
            pmax,
            samples,
            period_est,
            phase_error,
            resyncs,
            late,
            settle,
        ) = match self.state.lock() {
            Ok(guard) => {
                let mut values: Vec<i64> = Vec::with_capacity(WINDOW);
                let take = guard.written.min(WINDOW);
                for i in 0..take {
                    let v = guard.intervals[i];
                    if v > 0 {
                        values.push(v);
                    }
                }
                values.sort_unstable();
                let pick = |q: f64| -> i64 {
                    if values.is_empty() {
                        return 0;
                    }
                    let idx = ((values.len() as f64 - 1.0) * q).round() as usize;
                    values[idx.min(values.len() - 1)]
                };
                (
                    guard.mode,
                    guard.panel_period_ns,
                    guard.frames,
                    guard.timer_frames,
                    guard.timeouts,
                    pick(0.50),
                    pick(0.95),
                    values.last().copied().unwrap_or(0),
                    values.len(),
                    guard.period_est_ns,
                    guard.phase_error_ns,
                    guard.resyncs,
                    guard.late,
                    guard.settle,
                )
            }
            Err(_) => (Mode::Timer, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        };
        let panel_hz = if panel_period > 0 {
            1e9 / panel_period as f64
        } else {
            0.0
        };
        let period_hz = if period_est > 0 {
            1e9 / period_est as f64
        } else {
            0.0
        };
        serde_json::json!({
            "handle": handle,
            "mode": mode.as_str(),
            "target_hz": round3(target_hz),
            "panel_hz": round3(panel_hz),
            "period_hz": round3(period_hz),
            "divisor": divisor,
            "frames": frames,
            "timer_frames": timer_frames,
            "timeouts": timeouts,
            "samples": samples,
            "interval_p50_ms": round3(p50 as f64 / 1e6),
            "interval_p95_ms": round3(p95 as f64 / 1e6),
            "interval_max_ms": round3(pmax as f64 / 1e6),
            "phase_error_us": round3(phase_error as f64 / 1e3),
            "resyncs": resyncs,
            "late": late,
            "settle": settle,
            "stopped": self.is_stopped(),
            "seq": self.seq.load(Ordering::Acquire),
        })
    }
}

/// 保留 3 位小数（JSON 里避免打印一长串浮点尾数）。
fn round3(value: f64) -> f64 {
    if value.is_finite() {
        (value * 1000.0).round() / 1000.0
    } else {
        0.0
    }
}

/// 帧率 → 周期（纳秒），越界值夹到合法范围。
fn period_ns_from_hz(hz: f64) -> i64 {
    let safe_hz = if hz.is_finite() {
        hz.clamp(MIN_TARGET_HZ, MAX_TARGET_HZ)
    } else {
        DEFAULT_PANEL_HZ
    };
    ((1e9 / safe_hz).round() as i64).max(MIN_PERIOD_NS)
}

// ---------------------------------------------------------------------------
// 句柄注册表
// ---------------------------------------------------------------------------

/// `u64` 句柄 → 时钟实例。`0` 保留为失败值，永不分配。
static REGISTRY: LazyLock<Mutex<HashMap<u64, Arc<Clock>>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// 下一个句柄 id（从 1 起）。
static NEXT_HANDLE: AtomicU64 = AtomicU64::new(1);

/// 按句柄取时钟（不存在返回 `None`）。
fn lookup(handle: u64) -> Option<Arc<Clock>> {
    if handle == 0 {
        return None;
    }
    REGISTRY.lock().ok()?.get(&handle).cloned()
}

/// 探测一次面板合成周期（纳秒）；无合成返回 `0`。
///
/// 连续调用 `DwmFlush()` 并取返回时刻的差值：背靠背调用时每个差值就是一个
/// 合成周期。第一个差值是"从调用前到现在"的残段（可能只有半帧），必须丢掉；
/// 其余取中位数抗单次抖动。
fn probe_panel_period_ns() -> i64 {
    let mut samples: Vec<i64> = Vec::with_capacity(8);
    let mut prev = now_ns();
    let mut first = true;
    for _ in 0..9 {
        // SAFETY：无参数调用。
        if unsafe { DwmFlush() } != 0 {
            break;
        }
        let at = now_ns();
        let delta = at - prev;
        prev = at;
        if first {
            // 残段不是完整周期，丢弃（否则会把 240Hz 探成 260Hz）。
            first = false;
            continue;
        }
        // 只接受 1ms~100ms 的合理合成周期（1Hz~1000Hz）。
        if (1_000_000..=100_000_000).contains(&delta) {
            samples.push(delta);
        }
    }
    if samples.len() < 3 {
        return 0;
    }
    samples.sort_unstable();
    samples[samples.len() / 2]
}

// ---------------------------------------------------------------------------
// 导出
// ---------------------------------------------------------------------------

/// 模块能力位（`spk_abi_version` 的 `frame_clock` 字段）。
///
/// 恒 `true`：导出在编译期就存在；运行期是否真能锁相由 `spk_frameclock_probe`
/// 的 `composited` 决定（DWM 关闭时内部自动退化为定时器模式）。
pub(crate) fn exported() -> bool {
    true
}

/// 创建帧时钟（`target_hz` 为目标出帧率，如 240.0）。
///
/// Returns:
///     非零句柄；失败（句柄表满/锁中毒/计数器回绕）返回 `0`。
#[no_mangle]
pub extern "C" fn spk_frameclock_create(target_hz: c_double) -> u64 {
    catch_unwind(AssertUnwindSafe(|| {
        let handle = NEXT_HANDLE.fetch_add(1, Ordering::Relaxed);
        if handle == 0 {
            return 0;
        }
        let mut reg = match REGISTRY.lock() {
            Ok(g) => g,
            Err(_) => return 0,
        };
        if reg.len() >= MAX_HANDLES {
            return 0;
        }
        reg.insert(handle, Arc::new(Clock::new(target_hz)));
        handle
    }))
    .unwrap_or(0)
}

/// 调整目标帧率（可随时调用；不打断阻塞中的 `wait`）。
///
/// Returns:
///     `0` 成功；`-1` 非法参数；`-2` 非法句柄。
#[no_mangle]
pub extern "C" fn spk_frameclock_set_rate(handle: u64, target_hz: c_double) -> c_int {
    catch_to_status(crate::STATUS_INTERNAL, || {
        if !(target_hz.is_finite() && target_hz > 0.0) {
            return STATUS_INVALID_ARG;
        }
        let Some(clock) = lookup(handle) else {
            return STATUS_INVALID_HANDLE;
        };
        clock.set_rate(target_hz);
        STATUS_OK
    })
}

/// 阻塞到下一帧。
///
/// Args:
///     handle: `spk_frameclock_create` 返回的句柄。
///     timeout_ms: 本次等待上限（毫秒，必须 > 0）。
///
/// Returns:
///     `>0` 已出帧序号（从 1 递增）；`-1` 非法参数；`-2` 非法句柄；
///     `-3` 超时（调用方仍应出帧）；`-4` 已停止；`-5` 时钟不可用。
#[no_mangle]
pub extern "C" fn spk_frameclock_wait(handle: u64, timeout_ms: c_int) -> i64 {
    catch_unwind(AssertUnwindSafe(|| {
        if timeout_ms <= 0 {
            return i64::from(STATUS_INVALID_ARG);
        }
        let Some(clock) = lookup(handle) else {
            return i64::from(STATUS_INVALID_HANDLE);
        };
        match clock.wait_next(i64::from(timeout_ms) * 1_000_000) {
            Ok(seq) => seq as i64,
            Err(code) => i64::from(code),
        }
    }))
    .unwrap_or(i64::from(crate::STATUS_INTERNAL))
}

/// 置停止标志：阻塞中的 `wait` 最迟在一个合成周期后返回 `-4`。幂等。
#[no_mangle]
pub extern "C" fn spk_frameclock_stop(handle: u64) -> c_int {
    catch_to_status(crate::STATUS_INTERNAL, || {
        let Some(clock) = lookup(handle) else {
            return STATUS_INVALID_HANDLE;
        };
        clock.stop.store(true, Ordering::Release);
        STATUS_OK
    })
}

/// 清除停止标志，允许再次 `wait`。幂等。
#[no_mangle]
pub extern "C" fn spk_frameclock_resume(handle: u64) -> c_int {
    catch_to_status(crate::STATUS_INTERNAL, || {
        let Some(clock) = lookup(handle) else {
            return STATUS_INVALID_HANDLE;
        };
        clock.stop.store(false, Ordering::Release);
        STATUS_OK
    })
}

/// 销毁句柄。在途 `wait` 持有 `Arc`，不会悬垂（调用方仍应先 `stop` 并等线程退出）。
#[no_mangle]
pub extern "C" fn spk_frameclock_free(handle: u64) -> c_int {
    catch_to_status(crate::STATUS_INTERNAL, || {
        if handle == 0 {
            return STATUS_INVALID_ARG;
        }
        let removed = match REGISTRY.lock() {
            Ok(mut reg) => reg.remove(&handle).is_some(),
            Err(_) => false,
        };
        if removed { STATUS_OK } else { STATUS_INVALID_HANDLE }
    })
}

/// 统计 JSON（`mode` / `panel_hz` / `target_hz` / `divisor` / 间隔分位数等）。
///
/// 返回指针由 Rust 分配，调用方须先 `ctypes.string_at` 拷贝再
/// [`crate::spk_free_message`] 释放；失败返回 null。
#[no_mangle]
pub extern "C" fn spk_frameclock_stats(handle: u64) -> *mut c_char {
    catch_to_ptr(|| {
        let Some(clock) = lookup(handle) else {
            return std::ptr::null_mut();
        };
        alloc_json_message(&clock.stats_json(handle).to_string())
    })
}

/// 探测显示器合成能力与实测刷新率（诊断用，约阻塞 7 个合成周期）。
///
/// Returns:
///     JSON：`{"composited":bool,"refresh_hz":f64,"period_ms":f64,
///     "high_res_timer":bool,"samples":[...]}`；失败返回 null。
#[no_mangle]
pub extern "C" fn spk_frameclock_probe() -> *mut c_char {
    catch_to_ptr(|| {
        let mut enabled: i32 = 0;
        // SAFETY：写入本地变量，指针有效。
        let composed = unsafe { DwmIsCompositionEnabled(&mut enabled) } == 0 && enabled != 0;
        let mut samples: Vec<i64> = Vec::with_capacity(6);
        let mut prev = now_ns();
        let mut flush_failures = 0u32;
        for _ in 0..7 {
            // SAFETY：无参数调用。
            let hr = unsafe { DwmFlush() };
            let at = now_ns();
            if hr != 0 {
                flush_failures += 1;
                prev = at;
                continue;
            }
            let delta = at - prev;
            prev = at;
            if (1_000_000..=100_000_000).contains(&delta) {
                samples.push(delta);
            }
        }
        let period = if samples.is_empty() {
            0
        } else {
            let mut sorted = samples.clone();
            sorted.sort_unstable();
            sorted[sorted.len() / 2]
        };
        let timer = create_timer();
        let timer_ok = !timer.0.is_null();
        drop(timer);
        let payload = serde_json::json!({
            "composited": composed,
            "refresh_hz": if period > 0 { round3(1e9 / period as f64) } else { 0.0 },
            "period_ms": round3(period as f64 / 1e6),
            "high_res_timer": timer_ok,
            "samples_ms": samples
                .iter()
                .map(|v| round3(*v as f64 / 1e6))
                .collect::<Vec<f64>>(),
            "flush_failures": flush_failures,
        })
        .to_string();
        alloc_json_message(&payload)
    })
}

/// 单调时钟当前值（QPC 纳秒）。供 Python 侧把自身时间戳对齐到同一基准。
#[no_mangle]
pub extern "C" fn spk_frameclock_now_ns() -> i64 {
    catch_unwind(AssertUnwindSafe(now_ns)).unwrap_or(0)
}
