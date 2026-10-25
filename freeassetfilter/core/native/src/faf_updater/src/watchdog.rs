//! Idle-progress watchdog for the HTTP transfer phase.
//!
//! `ureq` has no portable "abort when the socket stops producing bytes" knob
//! across the supported 3.x range, so the downloader arms this watchdog for the
//! transport part of a download only. Every resolved address, sent request,
//! received header, redirect hop and flushed 64 KiB chunk refreshes
//! `last_progress_ms`. The watchdog is disarmed before hashing starts, so a
//! long local SHA-256 pass can never be mistaken for a network stall.
//!
//! Termination is injected via [`WatchdogAction`]; production supplies
//! [`ProcessExitAction`] while tests supply a recorder and never exit.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

/// Default "no new bytes" threshold.
pub const DEFAULT_IDLE_TIMEOUT_MS: u64 = 90_000;
/// Grace given to the download thread to finish a graceful pause/cancel.
pub const DEFAULT_CONTROL_GRACE_MS: u64 = 1_500;
/// Lower clamp for `FAF_UPDATER_IDLE_TIMEOUT_MS`.
pub const MIN_IDLE_TIMEOUT_MS: u64 = 100;
/// Upper clamp for `FAF_UPDATER_IDLE_TIMEOUT_MS`.
pub const MAX_IDLE_TIMEOUT_MS: u64 = 90_000;
/// Environment override read by the production entry point.
pub const ENV_IDLE_TIMEOUT_MS: &str = "FAF_UPDATER_IDLE_TIMEOUT_MS";

/// Tunables for one watchdog instance (production or injected in tests).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WatchdogConfig {
    pub idle_timeout_ms: u64,
    pub control_grace_ms: u64,
    pub poll_interval_ms: u64,
}

impl WatchdogConfig {
    /// Builds a production config, clamping the idle threshold to the
    /// documented range and deriving the control grace as `min(1500, idle)`.
    pub fn new(idle_timeout_ms: u64) -> Self {
        let idle_timeout_ms = idle_timeout_ms.clamp(MIN_IDLE_TIMEOUT_MS, MAX_IDLE_TIMEOUT_MS);
        Self {
            idle_timeout_ms,
            control_grace_ms: idle_timeout_ms.min(DEFAULT_CONTROL_GRACE_MS),
            poll_interval_ms: 10,
        }
    }

    /// Reads `FAF_UPDATER_IDLE_TIMEOUT_MS` (invalid values fall back to the
    /// default).
    pub fn from_env() -> Self {
        let raw = std::env::var(ENV_IDLE_TIMEOUT_MS).ok();
        match Self::parse_env_override(raw.as_deref()) {
            Some(idle_timeout_ms) => Self::new(idle_timeout_ms),
            None => Self::default(),
        }
    }

    /// Parses/validates a raw environment value. Returns `None` when the value
    /// is absent or not a number.
    pub fn parse_env_override(raw: Option<&str>) -> Option<u64> {
        let parsed = raw?.trim().parse::<u64>().ok()?;
        Some(parsed.clamp(MIN_IDLE_TIMEOUT_MS, MAX_IDLE_TIMEOUT_MS))
    }
}

impl Default for WatchdogConfig {
    fn default() -> Self {
        Self::new(DEFAULT_IDLE_TIMEOUT_MS)
    }
}

/// Actions the watchdog may take when a deadline is reached.
///
/// Production aborts the process; tests record the call instead.
pub trait WatchdogAction: Send + Sync + 'static {
    /// No new bytes for `idle_timeout_ms`.
    fn on_idle_timeout(&self);
    /// User pause/cancel acknowledged but not completed within the grace.
    fn on_control_abort(&self);
}

/// Production action: write nothing, leave the process immediately.
///
/// The owning download code writes the terminal response before arming the
/// abort path; by the time the watchdog fires, stdout is already flushed.
#[allow(dead_code)] // documented injectable action; the sidecar supplies its own.
pub struct ProcessExitAction;

impl WatchdogAction for ProcessExitAction {
    fn on_idle_timeout(&self) {
        std::process::exit(0);
    }

    fn on_control_abort(&self) {
        std::process::exit(0);
    }
}

/// Shared watchdog state. All timestamps are milliseconds since `epoch`.
#[derive(Debug)]
pub struct WatchdogState {
    epoch: Instant,
    last_progress_ms: AtomicU64,
    control_abort: AtomicBool,
    ack_written: AtomicBool,
    control_started_ms: AtomicU64,
    idle_timeout_fired: AtomicBool,
    control_abort_fired: AtomicBool,
}

impl WatchdogState {
    fn new() -> Self {
        Self {
            epoch: Instant::now(),
            last_progress_ms: AtomicU64::new(0),
            control_abort: AtomicBool::new(false),
            ack_written: AtomicBool::new(false),
            control_started_ms: AtomicU64::new(0),
            idle_timeout_fired: AtomicBool::new(false),
            control_abort_fired: AtomicBool::new(false),
        }
    }

    /// Milliseconds since this state was created.
    pub fn now_ms(&self) -> u64 {
        u64::try_from(self.epoch.elapsed().as_millis()).unwrap_or(u64::MAX)
    }

    /// Records transport progress (DNS/connect/headers/redirect/chunk).
    pub fn progress(&self) {
        self.last_progress_ms
            .store(self.now_ms(), Ordering::Release);
    }

    /// Timestamp of the most recent progress tick.
    #[allow(dead_code)] // diagnostic accessor; the monitor reads the field.
    pub fn last_progress_ms(&self) -> u64 {
        self.last_progress_ms.load(Ordering::Acquire)
    }

    /// User pause/cancel observed; starts the graceful-completion grace window.
    pub fn request_control_abort(&self) {
        // Timestamp first so the monitor never observes the flag with a stale
        // start time.
        self.control_started_ms
            .store(self.now_ms(), Ordering::Release);
        self.control_abort.store(true, Ordering::Release);
    }

    /// The control ack has been written and flushed.
    pub fn mark_ack_written(&self) {
        self.ack_written.store(true, Ordering::Release);
    }

    /// Whether the idle-timeout action ran.
    pub fn idle_timeout_fired(&self) -> bool {
        self.idle_timeout_fired.load(Ordering::Acquire)
    }

    /// Whether the control-abort action ran.
    #[allow(dead_code)] // asserted by the watchdog unit tests.
    pub fn control_abort_fired(&self) -> bool {
        self.control_abort_fired.load(Ordering::Acquire)
    }
}

/// Armed watchdog; dropping it disarms and joins the monitor thread.
#[derive(Debug)]
pub struct Watchdog {
    state: Arc<WatchdogState>,
    handle: Option<JoinHandle<()>>,
    armed: Arc<AtomicBool>,
}

impl Watchdog {
    /// Spawns the monitor thread for one download attempt.
    pub fn arm(config: WatchdogConfig, action: Arc<dyn WatchdogAction>) -> Self {
        let state = Arc::new(WatchdogState::new());
        let armed = Arc::new(AtomicBool::new(true));
        let loop_state = Arc::clone(&state);
        let loop_armed = Arc::clone(&armed);
        let handle = thread::spawn(move || run_loop(loop_state, loop_armed, config, action));
        Self {
            state,
            handle: Some(handle),
            armed,
        }
    }

    /// Shared state used to publish progress and control flags.
    pub fn state(&self) -> Arc<WatchdogState> {
        Arc::clone(&self.state)
    }

    /// Records one progress tick.
    #[allow(dead_code)] // test/diagnostic helper; download uses `state()`.
    pub fn progress(&self) {
        self.state.progress();
    }

    /// Stops the monitor and waits for the thread to exit.
    pub fn disarm(&mut self) {
        self.armed.store(false, Ordering::Release);
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }

    /// Whether the monitor thread is still armed.
    #[allow(dead_code)] // asserted by the watchdog unit tests.
    pub fn is_armed(&self) -> bool {
        self.armed.load(Ordering::Acquire)
    }
}

fn run_loop(
    state: Arc<WatchdogState>,
    armed: Arc<AtomicBool>,
    config: WatchdogConfig,
    action: Arc<dyn WatchdogAction>,
) {
    let poll = Duration::from_millis(config.poll_interval_ms.max(1));
    while armed.load(Ordering::Acquire) {
        thread::sleep(poll);
        if !armed.load(Ordering::Acquire) {
            break;
        }
        let now = state.now_ms();

        if state.control_abort.load(Ordering::Acquire) {
            // A graceful pause/cancel is in flight: never fire the idle
            // timeout, and only force the abort once the ack is on the wire
            // and the grace window has elapsed.
            if state.ack_written.load(Ordering::Acquire) {
                let started = state.control_started_ms.load(Ordering::Acquire);
                if now.saturating_sub(started) >= config.control_grace_ms
                    && !state.control_abort_fired.swap(true, Ordering::AcqRel)
                {
                    action.on_control_abort();
                }
            }
            if state.control_abort_fired.load(Ordering::Acquire) {
                armed.store(false, Ordering::Release);
                break;
            }
            continue;
        }

        let idle_for = now.saturating_sub(state.last_progress_ms.load(Ordering::Acquire));
        if idle_for >= config.idle_timeout_ms
            && !state.idle_timeout_fired.swap(true, Ordering::AcqRel)
        {
            action.on_idle_timeout();
            armed.store(false, Ordering::Release);
            break;
        }
    }
}

impl Drop for Watchdog {
    fn drop(&mut self) {
        self.disarm();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::{Shutdown, TcpListener, TcpStream};
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Mutex;

    struct RecordingWatchdogAction {
        idle: AtomicUsize,
        aborts: AtomicUsize,
        abort_socket: Mutex<Option<TcpStream>>,
    }

    impl RecordingWatchdogAction {
        fn new() -> Arc<Self> {
            Arc::new(Self {
                idle: AtomicUsize::new(0),
                aborts: AtomicUsize::new(0),
                abort_socket: Mutex::new(None),
            })
        }

        fn with_socket(socket: TcpStream) -> Arc<Self> {
            Arc::new(Self {
                idle: AtomicUsize::new(0),
                aborts: AtomicUsize::new(0),
                abort_socket: Mutex::new(Some(socket)),
            })
        }

        fn idle_count(&self) -> usize {
            self.idle.load(Ordering::SeqCst)
        }

        fn abort_count(&self) -> usize {
            self.aborts.load(Ordering::SeqCst)
        }
    }

    impl WatchdogAction for RecordingWatchdogAction {
        fn on_idle_timeout(&self) {
            self.idle.fetch_add(1, Ordering::SeqCst);
        }

        fn on_control_abort(&self) {
            self.aborts.fetch_add(1, Ordering::SeqCst);
            if let Ok(mut guard) = self.abort_socket.lock() {
                if let Some(socket) = guard.take() {
                    let _ = socket.shutdown(Shutdown::Both);
                }
            }
        }
    }

    fn wait_for(mut predicate: impl FnMut() -> bool) -> bool {
        let deadline = Instant::now() + Duration::from_secs(3);
        while Instant::now() < deadline {
            if predicate() {
                return true;
            }
            thread::sleep(Duration::from_millis(5));
        }
        predicate()
    }

    #[test]
    fn idle_timeout_fires_once_and_keeps_part_file() {
        let dir = tempfile::tempdir().expect("tempdir");
        let part = dir.path().join("installer.exe.part");
        std::fs::write(&part, b"partial-bytes").expect("write part");

        let action = RecordingWatchdogAction::new();
        let config = WatchdogConfig {
            idle_timeout_ms: 100,
            control_grace_ms: DEFAULT_CONTROL_GRACE_MS,
            poll_interval_ms: 10,
        };
        let mut watchdog = Watchdog::arm(config, action.clone());

        assert!(
            wait_for(|| action.idle_count() == 1),
            "idle timeout must fire"
        );
        thread::sleep(Duration::from_millis(80));
        assert_eq!(action.idle_count(), 1, "timeout fires exactly once");
        assert_eq!(action.abort_count(), 0);
        assert_eq!(
            std::fs::read(&part).expect("part readable"),
            b"partial-bytes",
            "part file must survive for resume"
        );
        assert!(watchdog.state().idle_timeout_fired());

        let started = Instant::now();
        watchdog.disarm();
        assert!(
            started.elapsed() < Duration::from_millis(200),
            "early return must disarm+join quickly"
        );
        assert!(!watchdog.is_armed());
    }

    #[test]
    fn control_abort_after_grace_unblocks_stalled_reader_and_keeps_part() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let addr = listener.local_addr().expect("addr");
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\nfirst-chunk")
                .expect("write headers");
            stream.flush().ok();
            // Stall until the client side is shut down by the abort action.
            let mut buffer = [0u8; 64];
            while matches!(stream.read(&mut buffer), Ok(read) if read > 0) {}
        });

        let mut reader = TcpStream::connect(addr).expect("connect");
        let action = RecordingWatchdogAction::with_socket(reader.try_clone().expect("clone"));

        let dir = tempfile::tempdir().expect("tempdir");
        let part_path = dir.path().join("installer.exe.part");
        let worker_part = part_path.clone();
        let worker = thread::spawn(move || {
            let mut buffer = [0u8; 4096];
            let mut file = std::fs::File::create(&worker_part).expect("create part");
            loop {
                match reader.read(&mut buffer) {
                    Ok(0) | Err(_) => break,
                    Ok(read) => file.write_all(&buffer[..read]).expect("write part"),
                }
            }
        });

        let config = WatchdogConfig {
            idle_timeout_ms: 10_000,
            control_grace_ms: 200,
            poll_interval_ms: 10,
        };
        let mut watchdog = Watchdog::arm(config, action.clone());
        let state = watchdog.state();
        state.request_control_abort();
        state.mark_ack_written();

        assert!(
            wait_for(|| action.abort_count() == 1),
            "abort hook must run after grace"
        );
        assert_eq!(
            action.idle_count(),
            0,
            "pause/cancel must win over idle timeout"
        );
        assert!(watchdog.state().control_abort_fired());

        let started = Instant::now();
        worker.join().expect("download thread");
        assert!(
            started.elapsed() < Duration::from_millis(200),
            "stalled reader must unblock quickly after abort"
        );
        let bytes = std::fs::read(&part_path).expect("part");
        assert!(!bytes.is_empty(), "part file retained for resume");

        watchdog.disarm();
        server.join().expect("server thread");
    }

    #[test]
    fn early_return_disarms_and_joins_within_budget() {
        let action = RecordingWatchdogAction::new();
        let mut watchdog = Watchdog::arm(WatchdogConfig::default(), action.clone());
        watchdog.progress();

        let started = Instant::now();
        watchdog.disarm();
        assert!(
            started.elapsed() < Duration::from_millis(200),
            "bad_params/unsafe_url/http_status early returns must not block"
        );
        assert!(!watchdog.is_armed());
        watchdog.disarm();
        assert_eq!(action.idle_count(), 0);
        assert_eq!(action.abort_count(), 0);
    }

    #[test]
    fn pending_control_suppresses_idle_timeout_until_grace() {
        let action = RecordingWatchdogAction::new();
        let config = WatchdogConfig {
            idle_timeout_ms: 60,
            control_grace_ms: 300,
            poll_interval_ms: 10,
        };
        let mut watchdog = Watchdog::arm(config, action.clone());
        let state = watchdog.state();
        state.request_control_abort();
        state.mark_ack_written();

        thread::sleep(Duration::from_millis(180));
        assert_eq!(action.idle_count(), 0, "graceful pause must not timeout");
        assert_eq!(action.abort_count(), 0, "grace not exceeded yet");

        assert!(wait_for(|| action.abort_count() == 1));
        assert_eq!(action.idle_count(), 0);
        watchdog.disarm();
    }

    #[test]
    fn control_abort_never_fires_before_the_ack_is_written() {
        let action = RecordingWatchdogAction::new();
        let config = WatchdogConfig {
            idle_timeout_ms: 10_000,
            control_grace_ms: 100,
            poll_interval_ms: 10,
        };
        let mut watchdog = Watchdog::arm(config, action.clone());
        let state = watchdog.state();
        state.request_control_abort();

        thread::sleep(Duration::from_millis(250));
        assert_eq!(
            action.abort_count(),
            0,
            "the ack must be on the wire before the forced abort can fire"
        );
        assert_eq!(
            action.idle_count(),
            0,
            "control suppresses the idle timeout"
        );

        state.mark_ack_written();
        assert!(
            wait_for(|| action.abort_count() == 1),
            "abort must fire within the grace window after the ack"
        );
        watchdog.disarm();
    }

    #[test]
    fn env_override_is_clamped_and_default_is_90s() {
        let default = WatchdogConfig::default();
        assert_eq!(default.idle_timeout_ms, DEFAULT_IDLE_TIMEOUT_MS);
        assert_eq!(default.control_grace_ms, DEFAULT_CONTROL_GRACE_MS);

        assert_eq!(WatchdogConfig::parse_env_override(Some("50")), Some(100));
        assert_eq!(
            WatchdogConfig::parse_env_override(Some("200000")),
            Some(90_000)
        );
        assert_eq!(WatchdogConfig::parse_env_override(Some("1234")), Some(1234));
        assert_eq!(WatchdogConfig::parse_env_override(Some("nope")), None);
        assert_eq!(WatchdogConfig::parse_env_override(None), None);

        let short = WatchdogConfig::new(200);
        assert_eq!(short.idle_timeout_ms, 200);
        assert_eq!(short.control_grace_ms, 200, "grace = min(1500, idle)");
    }
}
