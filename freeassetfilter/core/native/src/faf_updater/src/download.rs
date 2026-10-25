//! Download state machine: URL validation, manual redirects, resume, transfer,
//! pause/cancel, streaming SHA-256, atomic replacement and `verify`.
//!
//! A download is one `DownloadControl` (request-level pause/cancel flags plus
//! the watchdog handle used to start the graceful-abort grace window) driven
//! through one `DownloadRuntime` (watchdog tunables/action, retry policy and
//! the single-flight gate).
//!
//! Terminal result shapes (C1):
//!
//! * `done` - hash matched, part moved into place, old installers cleaned up.
//! * `paused` - part + `.part.json` retained for the next `download` resume.
//! * `cancelled` - part/meta (and, during verification, the final file) gone.
//!
//! Failures before the first body byte may be retried (network/5xx only);
//! failures after bytes were written retain the part so a later request can
//! resume. `timeout` is never retried: the watchdog owns that decision.

use std::fs;
use std::io::{self, Read, Write};
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::FromRawHandle;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU8, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use url::{Host, Url};
use windows_sys::Win32::Foundation::{
    CloseHandle, BOOL, GENERIC_READ, HANDLE, INVALID_HANDLE_VALUE,
};
use windows_sys::Win32::Storage::FileSystem::{
    GetFileInformationByHandle, MoveFileExW, BY_HANDLE_FILE_INFORMATION,
    FILE_ATTRIBUTE_REPARSE_POINT, FILE_FLAG_OPEN_REPARSE_POINT, FILE_FLAG_SEQUENTIAL_SCAN,
    FILE_SHARE_READ, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH, OPEN_EXISTING,
};

use crate::error::{AppError, ErrorCode};
use crate::http::{apply_common_headers, download_agent};
use crate::protocol::{DownloadState, Event, Response};
use crate::state::{self, PartMeta};
use crate::watchdog::{Watchdog, WatchdogAction, WatchdogConfig, WatchdogState};

/// Smallest accepted `expected_size` (1 MiB).
pub const MIN_EXPECTED_SIZE: u64 = 1 << 20;
/// Largest accepted `expected_size` (2 GiB).
pub const MAX_EXPECTED_SIZE: u64 = 2 << 30;
/// Manual redirect budget (C1: at most five hops).
pub const MAX_REDIRECTS: usize = 5;
/// Body read/write granularity; also the watchdog progress cadence.
pub const CHUNK_SIZE: usize = 64 * 1024;
/// Maximum interval between two `progress` events.
pub const PROGRESS_INTERVAL: Duration = Duration::from_millis(150);
/// Cancel is honoured at most this many bytes apart while hashing.
pub const VERIFY_CANCEL_GRANULARITY: u64 = 4 * 1024 * 1024;
/// Bytes per read while hashing the finished part.
const VERIFY_CHUNK_SIZE: usize = 256 * 1024;
/// Retry backoff slices; interleaved with progress ticks and control checks.
const RETRY_SLEEP_SLICE: Duration = Duration::from_millis(50);

const PAUSE_FLAG: u8 = 1 << 0;
const CANCEL_FLAG: u8 = 1 << 1;
const VERIFYING_FLAG: u8 = 1 << 2;

/// Request-level pause/cancel control shared with the stdin reader.
///
/// The reader validates `params.target`, then either sets a flag (accepted) or
/// leaves the control untouched (rejected). The download thread polls the flags
/// every 64 KiB of body data and every 4 MiB while hashing.
#[derive(Debug, Default)]
pub struct DownloadControl {
    flags: AtomicU8,
    watchdog: Mutex<Option<Arc<WatchdogState>>>,
    /// Set once the stdin reader flushed the pause/cancel ack. The worker may
    /// attach its watchdog after that point, so the bit is replayed in
    /// [`Self::attach_watchdog`].
    acknowledged: AtomicBool,
}

impl DownloadControl {
    /// Creates an idle control (nothing requested yet).
    pub fn new() -> Self {
        Self::default()
    }

    /// Clears request-level flags before a freshly accepted `download`.
    ///
    /// Must be called by the dispatcher, never by the download thread: a pause
    /// that arrived before the worker started has to survive until the worker
    /// observes it.
    pub fn reset_for_request(&self) {
        self.flags.store(0, Ordering::Release);
        self.acknowledged.store(false, Ordering::Release);
    }

    /// Requests a graceful pause. Returns `false` while verifying.
    pub fn request_pause(&self) -> bool {
        loop {
            let current = self.flags.load(Ordering::Acquire);
            if current & VERIFYING_FLAG != 0 {
                return false;
            }
            if current & PAUSE_FLAG != 0 {
                return true;
            }
            if self
                .flags
                .compare_exchange(
                    current,
                    current | PAUSE_FLAG,
                    Ordering::AcqRel,
                    Ordering::Acquire,
                )
                .is_ok()
            {
                return true;
            }
        }
    }

    /// Requests cancellation. Always accepted, including while verifying.
    pub fn request_cancel(&self) -> bool {
        self.flags.fetch_or(CANCEL_FLAG, Ordering::AcqRel);
        true
    }

    /// Whether a pause is pending.
    pub fn pause_requested(&self) -> bool {
        self.flags.load(Ordering::Acquire) & PAUSE_FLAG != 0
    }

    /// Whether a cancel is pending.
    pub fn cancel_requested(&self) -> bool {
        self.flags.load(Ordering::Acquire) & CANCEL_FLAG != 0
    }

    /// Whether the download already entered the internal verification phase.
    #[allow(dead_code)] // state accessor asserted by the tests; no production caller.
    pub fn is_verifying(&self) -> bool {
        self.flags.load(Ordering::Acquire) & VERIFYING_FLAG != 0
    }

    /// Marks the start of the hash/replace phase (pause becomes unacceptable).
    pub fn mark_verifying(&self) {
        self.flags.fetch_or(VERIFYING_FLAG, Ordering::AcqRel);
    }

    /// Clears the verification marker once the request reached a terminal state.
    pub fn clear_verifying(&self) {
        self.flags.fetch_and(!VERIFYING_FLAG, Ordering::AcqRel);
    }

    /// Publishes the watchdog state so control handlers can start the grace.
    pub fn attach_watchdog(&self, watchdog: Arc<WatchdogState>) {
        // Store first, then replay any control/ack state observed before the
        // download thread armed its watchdog. Reading the flags before the
        // store would lose a pause/cancel that lands in between: the control
        // handler would see no watchdog to notify and the forced-abort grace
        // would never start. The reader thread sets the flag before it takes
        // the watchdog slot lock, so replaying under the slot lock is complete.
        if let Ok(mut slot) = self.watchdog.lock() {
            *slot = Some(Arc::clone(&watchdog));
            if self.pause_requested() || self.cancel_requested() {
                watchdog.request_control_abort();
            }
            if self.acknowledged.load(Ordering::Acquire) {
                watchdog.mark_ack_written();
            }
        }
    }

    /// Drops the watchdog handle (the monitor is already disarmed).
    pub fn detach_watchdog(&self) {
        if let Ok(mut slot) = self.watchdog.lock() {
            *slot = None;
        }
    }

    /// Mirrors `control_started_ms`/`control_abort` into the attached watchdog.
    pub fn request_watchdog_abort(&self) {
        if let Ok(slot) = self.watchdog.lock() {
            if let Some(watchdog) = slot.as_ref() {
                watchdog.request_control_abort();
            }
        }
    }

    /// Mirrors "ack already flushed" into the attached watchdog.
    pub fn acknowledge_control(&self) {
        self.acknowledged.store(true, Ordering::Release);
        if let Ok(slot) = self.watchdog.lock() {
            if let Some(watchdog) = slot.as_ref() {
                watchdog.mark_ack_written();
            }
        }
    }
}

/// Single-flight guard implemented by the runtime.
pub trait DownloadGate: Send + Sync {
    /// Attempts to become the only active download.
    fn try_acquire(&self) -> bool;
    /// Releases a previously acquired slot.
    fn release(&self);
}

/// Process-local gate: one download at a time.
#[derive(Debug, Default)]
pub struct ExclusiveDownloadGate {
    busy: AtomicBool,
}

impl ExclusiveDownloadGate {
    /// Const constructor so a production static can hold the gate.
    pub const fn new() -> Self {
        Self {
            busy: AtomicBool::new(false),
        }
    }
}

impl DownloadGate for ExclusiveDownloadGate {
    fn try_acquire(&self) -> bool {
        self.busy
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
    }

    fn release(&self) {
        self.busy.store(false, Ordering::Release);
    }
}

/// Production gate shared by every `download` command.
static PRODUCTION_GATE: ExclusiveDownloadGate = ExclusiveDownloadGate::new();

struct StaticGate(&'static ExclusiveDownloadGate);

impl DownloadGate for StaticGate {
    fn try_acquire(&self) -> bool {
        self.0.try_acquire()
    }

    fn release(&self) {
        self.0.release();
    }
}

/// RAII gate slot; dropping it lets the next download in.
struct GateGuard {
    gate: Arc<dyn DownloadGate>,
}

impl GateGuard {
    fn acquire(gate: Arc<dyn DownloadGate>) -> Result<Self, AppError> {
        if gate.try_acquire() {
            Ok(Self { gate })
        } else {
            Err(AppError::new(
                ErrorCode::Busy,
                "已有下载任务正在进行，请稍后再试",
            ))
        }
    }
}

impl Drop for GateGuard {
    fn drop(&mut self) {
        self.gate.release();
    }
}

/// Retry policy for failures observed before the first body byte.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RetryPolicy {
    /// Total attempts (the first try counts as one).
    pub max_attempts: u32,
    /// Delay before retry N (index 0 = delay before the second attempt).
    pub backoff: Vec<Duration>,
}

impl RetryPolicy {
    /// Production policy: three attempts, 1s/2s/4s backoff.
    pub fn standard() -> Self {
        Self {
            max_attempts: 3,
            backoff: vec![
                Duration::from_secs(1),
                Duration::from_secs(2),
                Duration::from_secs(4),
            ],
        }
    }

    /// Deterministic policy for tests: three attempts, no waiting.
    #[allow(dead_code)] // used through `DownloadRuntime::isolated` and the tests.
    pub fn immediate() -> Self {
        Self {
            max_attempts: 3,
            backoff: vec![Duration::ZERO; 3],
        }
    }

    fn delay_before(&self, retry_index: u32) -> Duration {
        let index = retry_index.saturating_sub(1) as usize;
        self.backoff.get(index).copied().unwrap_or(Duration::ZERO)
    }
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self::standard()
    }
}

/// Everything one `download` request needs beyond its own params/control.
pub struct DownloadRuntime {
    pub watchdog_config: WatchdogConfig,
    pub watchdog_action: Arc<dyn WatchdogAction>,
    pub retry: RetryPolicy,
    pub gate: Arc<dyn DownloadGate>,
}

impl DownloadRuntime {
    /// Runtime used by the command dispatcher: the process-wide busy gate and
    /// the production retry policy.
    pub fn production(
        watchdog_config: WatchdogConfig,
        watchdog_action: Arc<dyn WatchdogAction>,
    ) -> Self {
        Self {
            watchdog_config,
            watchdog_action,
            retry: RetryPolicy::standard(),
            gate: Arc::new(StaticGate(&PRODUCTION_GATE)),
        }
    }

    /// Runtime for unit tests: fresh gate per call, no backoff.
    #[allow(dead_code)] // used by `execute_download` and the unit tests only.
    pub fn isolated(
        watchdog_config: WatchdogConfig,
        watchdog_action: Arc<dyn WatchdogAction>,
    ) -> Self {
        Self {
            watchdog_config,
            watchdog_action,
            retry: RetryPolicy::immediate(),
            gate: Arc::new(ExclusiveDownloadGate::new()),
        }
    }
}

/// Validated `download` parameters.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DownloadParams {
    pub source_url: String,
    pub dest_path: PathBuf,
    pub expected_sha256: String,
    pub expected_size: u64,
    pub allow_insecure_localhost: bool,
}

impl DownloadParams {
    /// Parses and validates the `download` command payload.
    pub fn from_value(value: &Value) -> Result<Self, AppError> {
        let object = value
            .as_object()
            .ok_or_else(|| bad_params("download 参数必须是 JSON 对象"))?;

        let source_url = object
            .get("source_url")
            .and_then(Value::as_str)
            .filter(|url| !url.is_empty())
            .ok_or_else(|| bad_params("download.source_url 缺失或不是字符串"))?
            .to_owned();

        let dest_raw = object
            .get("dest_path")
            .and_then(Value::as_str)
            .filter(|path| !path.is_empty())
            .ok_or_else(|| bad_params("download.dest_path 缺失或不是字符串"))?;
        let dest_path = PathBuf::from(dest_raw);
        if !dest_path.is_absolute() {
            return Err(bad_params("download.dest_path 必须是绝对路径"));
        }
        if dest_path
            .components()
            .any(|component| matches!(component, std::path::Component::ParentDir))
        {
            return Err(bad_params("download.dest_path 不能包含 .."));
        }

        let expected_sha256 = object
            .get("expected_sha256")
            .and_then(Value::as_str)
            .filter(|hash| is_sha256_hex(hash))
            .ok_or_else(|| bad_params("download.expected_sha256 必须是 64 位十六进制字符串"))?
            .to_ascii_lowercase();

        let expected_size = object
            .get("expected_size")
            .and_then(Value::as_u64)
            .ok_or_else(|| bad_params("download.expected_size 缺失或不是整数"))?;
        if !(MIN_EXPECTED_SIZE..=MAX_EXPECTED_SIZE).contains(&expected_size) {
            return Err(bad_params("download.expected_size 超出 1 MiB..2 GiB 范围"));
        }

        let allow_insecure_localhost = match object.get("allow_insecure_localhost") {
            None => false,
            Some(value) => value
                .as_bool()
                .ok_or_else(|| bad_params("download.allow_insecure_localhost 必须是布尔值"))?,
        };

        let raw_name = dest_path
            .file_name()
            .and_then(std::ffi::OsStr::to_str)
            .ok_or_else(|| bad_params("download.dest_path 缺少文件名"))?;
        if !raw_name.to_ascii_lowercase().ends_with(".exe") {
            return Err(bad_params("download.dest_path 必须以 .exe 结尾"));
        }
        let sanitized = sanitize_asset_name(raw_name)?;
        if sanitized != raw_name {
            return Err(bad_params("download.dest_path 文件名不是规范的安全文件名"));
        }

        Ok(Self {
            source_url,
            dest_path,
            expected_sha256,
            expected_size,
            allow_insecure_localhost,
        })
    }
}

/// Terminal response sink. Implementations must flush after every line.
pub trait DownloadSink {
    /// Emits one asynchronous event.
    fn event(&mut self, event: &Event) -> io::Result<()>;
    /// Emits the final response envelope.
    fn response(&mut self, response: &Response) -> io::Result<()>;
}

/// Terminal download summary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DownloadReport {
    pub state: DownloadState,
    pub path: PathBuf,
    pub downloaded: u64,
    /// Actual streaming SHA-256; `None` for paused/cancelled results.
    pub sha256: Option<String>,
}

/// Runs one download request and writes its terminal response into `sink`.
///
/// Convenience entry point for isolated callers and tests: each call gets a
/// fresh single-flight gate and the deterministic retry policy. The sidecar
/// uses [`execute_download_with_control`] with [`DownloadRuntime::production`]
/// and a shared [`DownloadControl`], so pause/cancel can reach a live download.
#[allow(dead_code)] // isolated convenience entry point used by the unit tests only.
pub fn execute_download(
    id: &str,
    params: &DownloadParams,
    sink: &mut dyn DownloadSink,
    watchdog_config: WatchdogConfig,
    watchdog_action: Arc<dyn WatchdogAction>,
) -> Result<DownloadReport, AppError> {
    let runtime = DownloadRuntime::isolated(watchdog_config, watchdog_action);
    let control = DownloadControl::new();
    execute_download_with_control(id, params, sink, &control, &runtime)
}

/// Control-aware download entry point.
///
/// `control` must already be registered for this request id and reset once at
/// acceptance (see [`DownloadControl::reset_for_request`]); flags set before
/// this call are honoured before any network or filesystem work.
pub fn execute_download_with_control(
    id: &str,
    params: &DownloadParams,
    sink: &mut dyn DownloadSink,
    control: &DownloadControl,
    runtime: &DownloadRuntime,
) -> Result<DownloadReport, AppError> {
    let result = run_download(id, params, sink, control, runtime);
    let envelope = match &result {
        Ok(report) => Response::success(
            id,
            json!({
                "state": state_name(report.state),
                "path": report.path.to_string_lossy(),
                "downloaded": report.downloaded,
                "sha256": report.sha256,
            }),
        ),
        Err(error) => Response::failure(id, error),
    };
    if let Err(write_error) = sink.response(&envelope) {
        if result.is_ok() {
            return Err(io_error("写入下载结果失败", write_error));
        }
    }
    result
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ControlOutcome {
    Pause,
    Cancel,
}

fn control_outcome(control: &DownloadControl) -> Option<ControlOutcome> {
    if control.cancel_requested() {
        Some(ControlOutcome::Cancel)
    } else if control.pause_requested() {
        Some(ControlOutcome::Pause)
    } else {
        None
    }
}

struct AttemptFailure {
    error: AppError,
    /// Whether the state machine may retry at all (only before first byte).
    auto_retry: bool,
}

impl AttemptFailure {
    fn fatal(error: AppError) -> Self {
        Self {
            error,
            auto_retry: false,
        }
    }

    fn from_transport(error: AppError) -> Self {
        let auto_retry = matches!(error.code, ErrorCode::Network);
        Self { error, auto_retry }
    }
}

impl From<AppError> for AttemptFailure {
    fn from(error: AppError) -> Self {
        Self::fatal(error)
    }
}

enum AttemptOutcome {
    Completed(u64),
    Paused(u64),
    Cancelled(u64),
}

/// Arms the idle watchdog and keeps the control's handle in sync.
struct WatchdogGuard<'a> {
    watchdog: Option<Watchdog>,
    state: Arc<WatchdogState>,
    control: &'a DownloadControl,
}

impl<'a> WatchdogGuard<'a> {
    fn arm(
        config: WatchdogConfig,
        action: Arc<dyn WatchdogAction>,
        control: &'a DownloadControl,
    ) -> Self {
        let watchdog = Watchdog::arm(config, action);
        let state = watchdog.state();
        state.progress();
        control.attach_watchdog(Arc::clone(&state));
        Self {
            watchdog: Some(watchdog),
            state,
            control,
        }
    }

    fn state(&self) -> &Arc<WatchdogState> {
        &self.state
    }

    fn disarm(&mut self) {
        if let Some(mut watchdog) = self.watchdog.take() {
            watchdog.disarm();
        }
        self.control.detach_watchdog();
    }
}

impl Drop for WatchdogGuard<'_> {
    fn drop(&mut self) {
        self.disarm();
    }
}

fn run_download(
    id: &str,
    params: &DownloadParams,
    sink: &mut dyn DownloadSink,
    control: &DownloadControl,
    runtime: &DownloadRuntime,
) -> Result<DownloadReport, AppError> {
    // The busy guard comes first: a rejected request must not touch any state.
    let _gate = GateGuard::acquire(Arc::clone(&runtime.gate))?;

    let initial = validate_download_url(&params.source_url, params.allow_insecure_localhost)?;
    let dest = params.dest_path.as_path();
    if let Some(parent) = dest.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent).map_err(|error| io_error("创建下载目录失败", error))?;
        }
    }

    let part = state::part_path(dest);
    let meta_path = state::meta_path(dest);

    // A pause/cancel accepted before the worker started is honoured before any
    // network or file mutation.
    if let Some(outcome) = control_outcome(control) {
        return finish_control(
            id,
            sink,
            dest,
            &part,
            &meta_path,
            part_length(&part),
            outcome,
            false,
        );
    }

    let mut watchdog = WatchdogGuard::arm(
        runtime.watchdog_config,
        Arc::clone(&runtime.watchdog_action),
        control,
    );
    emit_state(sink, id, DownloadState::Resolving)?;

    let agent = download_agent();
    let max_attempts = runtime.retry.max_attempts.max(1);
    let mut attempt = 0_u32;
    let downloaded = loop {
        if let Some(outcome) = control_outcome(control) {
            return finish_control(
                id,
                sink,
                dest,
                &part,
                &meta_path,
                part_length(&part),
                outcome,
                false,
            );
        }
        if attempt > 0 {
            let delay = runtime.retry.delay_before(attempt);
            if let Some(outcome) = sleep_with_control(delay, watchdog.state(), control) {
                return finish_control(
                    id,
                    sink,
                    dest,
                    &part,
                    &meta_path,
                    part_length(&part),
                    outcome,
                    false,
                );
            }
        }
        attempt += 1;
        match run_attempt(
            id,
            params,
            sink,
            control,
            &agent,
            &initial,
            &part,
            &meta_path,
            watchdog.state(),
        ) {
            Ok(AttemptOutcome::Completed(downloaded)) => break downloaded,
            Ok(AttemptOutcome::Paused(downloaded)) => {
                return finish_control(
                    id,
                    sink,
                    dest,
                    &part,
                    &meta_path,
                    downloaded,
                    ControlOutcome::Pause,
                    false,
                );
            }
            Ok(AttemptOutcome::Cancelled(downloaded)) => {
                return finish_control(
                    id,
                    sink,
                    dest,
                    &part,
                    &meta_path,
                    downloaded,
                    ControlOutcome::Cancel,
                    false,
                );
            }
            Err(failure) => {
                if !failure.auto_retry || attempt >= max_attempts {
                    return Err(failure.error);
                }
            }
        }
    };

    // Verification must not be subject to the idle watchdog: hashing a large
    // local file would look like a stalled network. Mark first so a pause that
    // arrives after this point is rejected.
    control.mark_verifying();
    watchdog.disarm();
    emit_state(sink, id, DownloadState::Verifying)?;

    match hash_part(&part, control)? {
        HashOutcome::Cancelled => finish_verifying_cancel(id, sink, dest, &part, &meta_path),
        HashOutcome::Hashed(actual) => {
            if actual != params.expected_sha256 {
                cleanup(&part, &meta_path)?;
                control.clear_verifying();
                return Err(AppError::new(
                    ErrorCode::ChecksumMismatch,
                    format!(
                        "安装包校验失败：期望 {}，实际 {actual}",
                        params.expected_sha256
                    ),
                ));
            }
            // A cancel racing the last hash block still wins over `done`.
            if control.cancel_requested() {
                return finish_verifying_cancel(id, sink, dest, &part, &meta_path);
            }
            replace_part(&part, dest)?;
            state::remove_file_if_exists(&meta_path)?;
            cleanup_old_installers(dest);
            control.clear_verifying();
            emit_state(sink, id, DownloadState::Done)?;
            Ok(DownloadReport {
                state: DownloadState::Done,
                path: dest.to_path_buf(),
                downloaded,
                sha256: Some(actual),
            })
        }
    }
}

fn finish_control(
    id: &str,
    sink: &mut dyn DownloadSink,
    dest: &Path,
    part: &Path,
    meta_path: &Path,
    downloaded: u64,
    outcome: ControlOutcome,
    remove_final: bool,
) -> Result<DownloadReport, AppError> {
    match outcome {
        ControlOutcome::Pause => {
            emit_state(sink, id, DownloadState::Paused)?;
            Ok(DownloadReport {
                state: DownloadState::Paused,
                path: dest.to_path_buf(),
                downloaded,
                sha256: None,
            })
        }
        ControlOutcome::Cancel => {
            cleanup(part, meta_path)?;
            if remove_final {
                state::remove_file_if_exists(dest)?;
            }
            emit_state(sink, id, DownloadState::Cancelled)?;
            Ok(DownloadReport {
                state: DownloadState::Cancelled,
                path: dest.to_path_buf(),
                downloaded,
                sha256: None,
            })
        }
    }
}

fn finish_verifying_cancel(
    id: &str,
    sink: &mut dyn DownloadSink,
    dest: &Path,
    part: &Path,
    meta_path: &Path,
) -> Result<DownloadReport, AppError> {
    cleanup(part, meta_path)?;
    state::remove_file_if_exists(dest)?;
    // The hash file handle has been dropped by `hash_part` returning.
    emit_state(sink, id, DownloadState::Cancelled)?;
    Ok(DownloadReport {
        state: DownloadState::Cancelled,
        path: dest.to_path_buf(),
        downloaded: part_length(dest),
        sha256: None,
    })
}

#[allow(clippy::too_many_arguments)]
fn run_attempt(
    id: &str,
    params: &DownloadParams,
    sink: &mut dyn DownloadSink,
    control: &DownloadControl,
    agent: &ureq::Agent,
    initial: &Url,
    part: &Path,
    meta_path: &Path,
    watch: &WatchdogState,
) -> Result<AttemptOutcome, AttemptFailure> {
    let (mut offset, mut if_range) = prepare_resume(params, part, meta_path)?;
    let mut restarted_after_bad_range = false;

    loop {
        let mut response = follow_redirects(
            agent,
            initial,
            params.allow_insecure_localhost,
            offset,
            if_range.as_deref(),
            watch,
        )
        .map_err(AttemptFailure::from_transport)?;

        if let Some(encoding) = response
            .headers()
            .get("Content-Encoding")
            .and_then(|value| value.to_str().ok())
        {
            if !encoding.eq_ignore_ascii_case("identity") {
                return Err(AttemptFailure::fatal(AppError::new(
                    ErrorCode::HttpStatus,
                    "服务器返回了压缩内容，无法按字节续传",
                )));
            }
        }

        let status = response.status().as_u16();
        match status {
            416 => {
                let part_len = part_length(part);
                if part_len != params.expected_size {
                    return Err(AttemptFailure::fatal(AppError::new(
                        ErrorCode::BadRange,
                        "服务器报告文件已完整，但本地分段长度不符",
                    )));
                }
                return Ok(AttemptOutcome::Completed(params.expected_size));
            }
            200 => {
                if let Some(length) = content_length(&response) {
                    if length != params.expected_size {
                        cleanup(part, meta_path)?;
                        return Err(AttemptFailure::fatal(size_mismatch(format!(
                            "服务器文件大小 {length} 与预期 {} 不符",
                            params.expected_size
                        ))));
                    }
                }
                // A 200 answer means the server ignored the range request; the
                // tail of this attempt writes from byte 0, so `if_range` is
                // dead from here on.
                offset = 0;
            }
            206 => {
                let raw = response
                    .headers()
                    .get("Content-Range")
                    .and_then(|value| value.to_str().ok())
                    .ok_or_else(|| {
                        AppError::new(ErrorCode::BadRange, "206 响应缺少 Content-Range")
                    })?;
                let (start, total) = parse_content_range(raw)?;
                let total = total.ok_or_else(|| {
                    AppError::new(ErrorCode::BadRange, "Content-Range 缺少总长度")
                })?;
                if total != params.expected_size {
                    cleanup(part, meta_path)?;
                    return Err(AttemptFailure::fatal(size_mismatch(format!(
                        "服务器总长度 {total} 与预期 {} 不符",
                        params.expected_size
                    ))));
                }
                if start != offset {
                    if restarted_after_bad_range {
                        return Err(AttemptFailure::fatal(AppError::new(
                            ErrorCode::BadRange,
                            "服务器返回的分段起点仍然错误",
                        )));
                    }
                    truncate_part(part)?;
                    offset = 0;
                    if_range = None;
                    restarted_after_bad_range = true;
                    continue;
                }
            }
            other => {
                let error =
                    AppError::new(ErrorCode::HttpStatus, format!("下载请求返回 HTTP {other}"));
                // Only 5xx is retryable; 4xx must surface immediately.
                return Err(AttemptFailure {
                    error,
                    auto_retry: (500..600).contains(&other),
                });
            }
        }

        let etag = response
            .headers()
            .get("ETag")
            .and_then(|value| value.to_str().ok())
            .map(str::to_owned);
        state::write_meta(
            meta_path,
            &PartMeta::new(
                params.source_url.clone(),
                etag.clone(),
                params.expected_size,
                params.expected_sha256.clone(),
                params.expected_size,
            ),
        )?;

        let mut file = open_part(part, status == 206 && offset > 0, offset)?;
        let mut downloaded = offset;
        let mut wrote_any = false;
        let mut reporter = ProgressReporter::new(id, params.expected_size, offset);
        emit_state(sink, id, DownloadState::Downloading)?;

        let mut reader = response.body_mut().as_reader();
        let mut buffer = vec![0_u8; CHUNK_SIZE];
        loop {
            if let Some(outcome) = control_outcome(control) {
                let _ = file.flush();
                return Ok(attempt_control(outcome, downloaded));
            }
            match reader.read(&mut buffer) {
                Ok(0) => break,
                Ok(read) => {
                    if let Some(outcome) = control_outcome(control) {
                        let _ = file.flush();
                        return Ok(attempt_control(outcome, downloaded));
                    }
                    let next = downloaded + read as u64;
                    if next > params.expected_size {
                        cleanup(part, meta_path)?;
                        return Err(AttemptFailure::fatal(size_mismatch(format!(
                            "下载数据超过预期大小 {}",
                            params.expected_size
                        ))));
                    }
                    file.write_all(&buffer[..read])
                        .map_err(|error| io_error("写入分段文件失败", error))?;
                    file.flush()
                        .map_err(|error| io_error("刷新分段文件失败", error))?;
                    wrote_any = true;
                    downloaded = next;
                    watch.progress();
                    reporter.on_bytes(sink, downloaded)?;
                }
                Err(error) => {
                    if watch.idle_timeout_fired() {
                        return Err(AttemptFailure::fatal(timeout_error()));
                    }
                    if let Some(outcome) = control_outcome(control) {
                        let _ = file.flush();
                        return Ok(attempt_control(outcome, downloaded));
                    }
                    // Bytes already on disk: keep the part and let the caller
                    // resume later; never retry blindly in-process.
                    return Err(AttemptFailure {
                        error: network_error(error),
                        auto_retry: !wrote_any,
                    });
                }
            }
        }

        if watch.idle_timeout_fired() {
            return Err(AttemptFailure::fatal(timeout_error()));
        }
        if downloaded < params.expected_size {
            let _ = file.flush();
            return Err(AttemptFailure {
                error: network_error("连接提前结束，下载未完成"),
                auto_retry: !wrote_any,
            });
        }
        if downloaded > params.expected_size {
            return Err(AttemptFailure::fatal(size_mismatch(format!(
                "下载完成但大小 {downloaded} 与预期 {} 不符",
                params.expected_size
            ))));
        }
        reporter.finish(sink, downloaded)?;
        return Ok(AttemptOutcome::Completed(downloaded));
    }
}

fn attempt_control(outcome: ControlOutcome, downloaded: u64) -> AttemptOutcome {
    match outcome {
        ControlOutcome::Pause => AttemptOutcome::Paused(downloaded),
        ControlOutcome::Cancel => AttemptOutcome::Cancelled(downloaded),
    }
}

fn sleep_with_control(
    delay: Duration,
    watch: &WatchdogState,
    control: &DownloadControl,
) -> Option<ControlOutcome> {
    let deadline = Instant::now() + delay;
    loop {
        if let Some(outcome) = control_outcome(control) {
            return Some(outcome);
        }
        let now = Instant::now();
        if now >= deadline {
            break;
        }
        let remaining = deadline.saturating_duration_since(now);
        std::thread::sleep(remaining.min(RETRY_SLEEP_SLICE));
        watch.progress();
    }
    control_outcome(control)
}

fn follow_redirects(
    agent: &ureq::Agent,
    initial: &Url,
    allow_insecure_localhost: bool,
    offset: u64,
    if_range: Option<&str>,
    watch: &WatchdogState,
) -> Result<ureq::http::Response<ureq::Body>, AppError> {
    let mut current = initial.clone();
    let mut hops = 0_usize;
    loop {
        watch.progress();
        let mut request = apply_common_headers(agent.get(current.as_str()));
        if offset > 0 {
            let range = format!("bytes={offset}-");
            request = request.header("Range", range.as_str());
            if let Some(etag) = if_range {
                request = request.header("If-Range", etag);
            }
        }
        let response = match request.call() {
            Ok(response) => response,
            Err(error) => {
                if watch.idle_timeout_fired() {
                    return Err(timeout_error());
                }
                return Err(map_transport_error(error));
            }
        };
        watch.progress();

        let status = response.status().as_u16();
        if (300..400).contains(&status) {
            if hops >= MAX_REDIRECTS {
                return Err(AppError::new(ErrorCode::UnsafeUrl, "重定向次数超过上限"));
            }
            let location = response
                .headers()
                .get("Location")
                .and_then(|value| value.to_str().ok())
                .map(str::to_owned)
                .ok_or_else(|| AppError::new(ErrorCode::HttpStatus, "重定向响应缺少 Location"))?;
            current = resolve_redirect(&current, &location, allow_insecure_localhost)?;
            hops += 1;
            continue;
        }
        return Ok(response);
    }
}

fn prepare_resume(
    params: &DownloadParams,
    part: &Path,
    meta_path: &Path,
) -> Result<(u64, Option<String>), AppError> {
    let part_len = match fs::metadata(part) {
        Ok(metadata) => Some(metadata.len()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => None,
        Err(error) => return Err(io_error("读取分段文件状态失败", error)),
    };
    let meta = state::load_meta(meta_path)?;
    if let (Some(length), Some(meta)) = (part_len, meta) {
        if meta.is_resumable(
            &params.source_url,
            &params.expected_sha256,
            params.expected_size,
            length,
        ) {
            return Ok((length, meta.etag));
        }
    }
    if part_len.is_some() {
        state::remove_file_if_exists(part)?;
    }
    state::remove_file_if_exists(meta_path)?;
    Ok((0, None))
}

fn open_part(part: &Path, append: bool, offset: u64) -> Result<fs::File, AppError> {
    if append {
        let file = fs::OpenOptions::new()
            .append(true)
            .open(part)
            .map_err(|error| io_error("打开分段文件续传失败", error))?;
        let length = file
            .metadata()
            .map_err(|error| io_error("读取分段文件长度失败", error))?
            .len();
        if length != offset {
            return Err(AppError::new(
                ErrorCode::BadRange,
                "分段文件长度在续传前发生变化",
            ));
        }
        Ok(file)
    } else {
        fs::File::create(part).map_err(|error| io_error("创建分段文件失败", error))
    }
}

fn truncate_part(part: &Path) -> Result<(), AppError> {
    fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open(part)
        .map(|_| ())
        .map_err(|error| io_error("重置分段文件失败", error))
}

fn part_length(part: &Path) -> u64 {
    fs::metadata(part).map(|meta| meta.len()).unwrap_or(0)
}

/// Atomically swaps the verified part into place.
///
/// `MoveFileExW` with `REPLACE_EXISTING` keeps the destination and the part on
/// the same volume (the part always lives next to `dest`), so the rename is the
/// only state change an observer can see. If the volume refuses the replace,
/// the fallback is remove-then-retry.
fn replace_part(part: &Path, dest: &Path) -> Result<(), AppError> {
    let from = wide_path(part);
    let to = wide_path(dest);
    let flags = MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH;
    if unsafe { MoveFileExW(from.as_ptr(), to.as_ptr(), flags) } != 0 {
        return Ok(());
    }
    let first = io::Error::last_os_error();
    match fs::remove_file(dest) {
        Ok(()) => {}
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => {
            return Err(io_error(
                &format!("移除旧安装包失败（替换错误：{first}）"),
                error,
            ))
        }
    }
    if unsafe { MoveFileExW(from.as_ptr(), to.as_ptr(), flags) } != 0 {
        Ok(())
    } else {
        Err(io_error("原子替换安装包失败", io::Error::last_os_error()))
    }
}

/// Best-effort removal of previous installer builds next to `dest`.
///
/// Failures are ignored: a locked old installer must never fail a download that
/// already verified. The destination itself is skipped, and no canonicalisation
/// is used because it would follow reparse points.
fn cleanup_old_installers(dest: &Path) {
    let Some(parent) = dest.parent() else {
        return;
    };
    let Ok(entries) = fs::read_dir(parent) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path == dest {
            continue;
        }
        let Ok(file_type) = entry.file_type() else {
            continue;
        };
        if !file_type.is_file() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().to_ascii_lowercase();
        if name.starts_with("freeassetfilter") && name.ends_with(".exe") {
            let _ = fs::remove_file(&path);
        }
    }
}

enum HashOutcome {
    Hashed(String),
    Cancelled,
}

/// Streams the part through SHA-256, checking for cancel every 4 MiB.
fn hash_part(path: &Path, control: &DownloadControl) -> Result<HashOutcome, AppError> {
    let mut file = fs::File::open(path).map_err(|error| io_error("打开待校验文件失败", error))?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; VERIFY_CHUNK_SIZE];
    let mut processed = 0_u64;
    let mut next_check = VERIFY_CANCEL_GRANULARITY;
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|error| io_error("读取待校验文件失败", error))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
        processed += read as u64;
        if processed >= next_check {
            if control.cancel_requested() {
                return Ok(HashOutcome::Cancelled);
            }
            next_check += VERIFY_CANCEL_GRANULARITY;
        }
    }
    if control.cancel_requested() {
        return Ok(HashOutcome::Cancelled);
    }
    Ok(HashOutcome::Hashed(hex_digest(
        hasher.finalize().as_slice(),
    )))
}

fn hash_reader(reader: &mut impl Read) -> Result<String, AppError> {
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; VERIFY_CHUNK_SIZE];
    loop {
        let read = reader
            .read(&mut buffer)
            .map_err(|error| io_error("读取文件失败", error))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(hex_digest(hasher.finalize().as_slice()))
}

fn hex_digest(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

/// Result of [`verify_file`]: hash match plus the opaque file identity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct VerifyReport {
    #[serde(rename = "match")]
    pub match_: bool,
    pub actual: String,
    pub volume_serial: u64,
    pub file_index: u64,
}

/// Streams `path` through SHA-256 and returns its identity for the launch check.
///
/// The handle is opened with `FILE_FLAG_OPEN_REPARSE_POINT` and reparse-point
/// files are rejected outright, so a junction or symlink can never be laundered
/// into an installer launch.
pub fn verify_file(path: &Path, expected_sha256: &str) -> Result<VerifyReport, AppError> {
    if !is_sha256_hex(expected_sha256) {
        return Err(bad_params("verify.sha256 必须是 64 位十六进制字符串"));
    }
    let expected = expected_sha256.to_ascii_lowercase();
    let handle = open_no_follow(path)?;
    let mut info: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    let status: BOOL = unsafe { GetFileInformationByHandle(handle, &mut info) };
    if status == 0 {
        let error = io::Error::last_os_error();
        unsafe { CloseHandle(handle) };
        return Err(io_error("读取文件身份失败", error));
    }
    if info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        unsafe { CloseHandle(handle) };
        return Err(AppError::new(
            ErrorCode::Io,
            "拒绝校验重解析点（符号链接/联接）文件",
        ));
    }
    let mut file = unsafe { fs::File::from_raw_handle(handle) };
    let actual = hash_reader(&mut file)?;
    Ok(VerifyReport {
        match_: actual == expected,
        actual,
        volume_serial: info.dwVolumeSerialNumber as u64,
        file_index: ((info.nFileIndexHigh as u64) << 32) | info.nFileIndexLow as u64,
    })
}

fn open_no_follow(path: &Path) -> Result<HANDLE, AppError> {
    let wide = wide_path(path);
    let handle = unsafe {
        CreateFileW(
            wide.as_ptr(),
            GENERIC_READ,
            FILE_SHARE_READ,
            std::ptr::null(),
            OPEN_EXISTING,
            FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_SEQUENTIAL_SCAN,
            std::ptr::null_mut(),
        )
    };
    if handle == INVALID_HANDLE_VALUE {
        return Err(io_error("打开文件失败", io::Error::last_os_error()));
    }
    Ok(handle)
}

fn wide_path(path: &Path) -> Vec<u16> {
    path.as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect()
}

// windows-sys 0.59 gates its `CreateFileW` binding behind `Win32_Security`,
// which this crate does not enable (and the plan forbids adding features), so
// the exact kernel32 signature is declared locally. `MoveFileExW` and
// `GetFileInformationByHandle` are not gated and stay on windows-sys.
#[link(name = "kernel32")]
extern "system" {
    fn CreateFileW(
        file_name: *const u16,
        desired_access: u32,
        share_mode: u32,
        security_attributes: *const core::ffi::c_void,
        creation_disposition: u32,
        flags_and_attributes: u32,
        template_file: HANDLE,
    ) -> HANDLE;
}

fn cleanup(part: &Path, meta_path: &Path) -> Result<(), AppError> {
    state::remove_file_if_exists(part)?;
    state::remove_file_if_exists(meta_path)
}

fn emit_state(sink: &mut dyn DownloadSink, id: &str, state: DownloadState) -> Result<(), AppError> {
    sink.event(&Event::State {
        id: id.to_owned(),
        state,
    })
    .map_err(|error| io_error("写入下载事件失败", error))
}

fn state_name(state: DownloadState) -> &'static str {
    match state {
        DownloadState::Resolving => "resolving",
        DownloadState::Downloading => "downloading",
        DownloadState::Paused => "paused",
        DownloadState::Verifying => "verifying",
        DownloadState::Done => "done",
        DownloadState::Cancelled => "cancelled",
    }
}

struct ProgressReporter<'a> {
    id: &'a str,
    total: u64,
    last_emit: Option<Instant>,
    last_emit_bytes: u64,
    window_start: Instant,
    window_bytes: u64,
    speed_bps: u64,
}

impl<'a> ProgressReporter<'a> {
    fn new(id: &'a str, total: u64, start: u64) -> Self {
        let now = Instant::now();
        Self {
            id,
            total,
            last_emit: None,
            last_emit_bytes: start,
            window_start: now,
            window_bytes: start,
            speed_bps: 0,
        }
    }

    fn on_bytes(&mut self, sink: &mut dyn DownloadSink, downloaded: u64) -> Result<(), AppError> {
        let now = Instant::now();
        let due = self
            .last_emit
            .map(|last| now.duration_since(last) >= PROGRESS_INTERVAL)
            .unwrap_or(true);
        if due {
            self.emit(sink, downloaded, now)?;
        }
        Ok(())
    }

    fn finish(&mut self, sink: &mut dyn DownloadSink, downloaded: u64) -> Result<(), AppError> {
        if self.last_emit.is_none() || self.last_emit_bytes != downloaded {
            self.emit(sink, downloaded, Instant::now())?;
        }
        Ok(())
    }

    fn emit(
        &mut self,
        sink: &mut dyn DownloadSink,
        downloaded: u64,
        now: Instant,
    ) -> Result<(), AppError> {
        let elapsed_ms = now.duration_since(self.window_start).as_millis() as u64;
        if elapsed_ms > 0 {
            self.speed_bps = downloaded
                .saturating_sub(self.window_bytes)
                .saturating_mul(1000)
                / elapsed_ms;
            self.window_start = now;
            self.window_bytes = downloaded;
        }
        sink.event(&Event::Progress {
            id: self.id.to_owned(),
            downloaded,
            total: self.total,
            speed_bps: self.speed_bps,
        })
        .map_err(|error| io_error("写入下载进度失败", error))?;
        self.last_emit = Some(now);
        self.last_emit_bytes = downloaded;
        Ok(())
    }
}

fn content_length(response: &ureq::http::Response<ureq::Body>) -> Option<u64> {
    response
        .headers()
        .get("Content-Length")?
        .to_str()
        .ok()?
        .parse()
        .ok()
}

fn parse_content_range(value: &str) -> Result<(u64, Option<u64>), AppError> {
    let value = value.trim();
    let rest = value
        .strip_prefix("bytes ")
        .or_else(|| value.strip_prefix("bytes="))
        .ok_or_else(|| AppError::new(ErrorCode::BadRange, "Content-Range 格式无效"))?;
    let (range, total) = rest
        .split_once('/')
        .ok_or_else(|| AppError::new(ErrorCode::BadRange, "Content-Range 缺少总长度"))?;
    let start = range
        .split_once('-')
        .map(|(start, _end)| start.trim())
        .filter(|start| *start != "*")
        .ok_or_else(|| AppError::new(ErrorCode::BadRange, "Content-Range 缺少起点"))?
        .parse::<u64>()
        .map_err(|_| AppError::new(ErrorCode::BadRange, "Content-Range 起点无效"))?;
    let total = if total.trim() == "*" {
        None
    } else {
        Some(
            total
                .trim()
                .parse::<u64>()
                .map_err(|_| AppError::new(ErrorCode::BadRange, "Content-Range 总长度无效"))?,
        )
    };
    Ok((start, total))
}

fn map_transport_error(error: ureq::Error) -> AppError {
    match error {
        ureq::Error::Timeout(_) => timeout_error(),
        ureq::Error::BadUri(message) => {
            AppError::new(ErrorCode::UnsafeUrl, format!("下载地址无效：{message}"))
        }
        ureq::Error::StatusCode(code) => {
            AppError::new(ErrorCode::HttpStatus, format!("下载请求返回 HTTP {code}"))
        }
        other => network_error(other),
    }
}

fn is_sha256_hex(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn bad_params(message: impl Into<String>) -> AppError {
    AppError::new(ErrorCode::BadParams, message)
}

fn size_mismatch(message: impl Into<String>) -> AppError {
    AppError::new(ErrorCode::SizeMismatch, message)
}

fn timeout_error() -> AppError {
    AppError::new(ErrorCode::Timeout, "下载长时间没有收到新数据（空闲超时）")
}

fn io_error(context: &str, error: io::Error) -> AppError {
    AppError::new(ErrorCode::Io, format!("{context}：{error}"))
}

fn network_error(error: impl std::fmt::Display) -> AppError {
    AppError::new(ErrorCode::Network, format!("网络请求失败：{error}"))
}

/// Validates one URL (initial request or redirect hop).
pub fn validate_download_url(raw: &str, allow_insecure_localhost: bool) -> Result<Url, AppError> {
    let url = Url::parse(raw).map_err(|error| unsafe_url(format!("无法解析下载地址：{error}")))?;
    if !url.username().is_empty() || url.password().is_some() {
        return Err(unsafe_url("下载地址不能包含用户名或密码"));
    }

    let host = url.host().ok_or_else(|| unsafe_url("下载地址缺少主机名"))?;
    let loopback = match host {
        Host::Ipv4(address) => address.is_loopback(),
        Host::Ipv6(address) => address.is_loopback(),
        Host::Domain(_) => false,
    };
    if allow_insecure_localhost && loopback {
        if matches!(url.scheme(), "http" | "https") {
            return Ok(url);
        }
        return Err(unsafe_url("本机回环地址只允许 http/https"));
    }

    if url.scheme() != "https" {
        return Err(unsafe_url("下载地址必须使用 https"));
    }
    if url.port_or_known_default() != Some(443) {
        return Err(unsafe_url("下载地址只允许 443 端口"));
    }
    let allowed = match host {
        Host::Domain(domain) => {
            let domain = domain.to_ascii_lowercase();
            domain == "github.com"
                || domain == "api.github.com"
                || domain.ends_with(".githubusercontent.com")
        }
        Host::Ipv4(_) | Host::Ipv6(_) => false,
    };
    if !allowed {
        return Err(unsafe_url("下载地址主机不在允许列表内"));
    }
    Ok(url)
}

/// Resolves a `Location` header against `base` and validates the result.
pub fn resolve_redirect(
    base: &Url,
    location: &str,
    allow_insecure_localhost: bool,
) -> Result<Url, AppError> {
    let resolved = base
        .join(location)
        .map_err(|error| unsafe_url(format!("无法解析重定向地址：{error}")))?;
    validate_download_url(resolved.as_str(), allow_insecure_localhost)
}

/// Normalizes a release asset name into a safe Windows file name.
///
/// Returns `Err(BadParams)` for Windows reserved names and empty results.
pub fn sanitize_asset_name(raw: &str) -> Result<String, AppError> {
    let basename = raw.rsplit(['/', '\\']).next().unwrap_or(raw);
    let mut cleaned = String::with_capacity(basename.len());
    for character in basename.chars() {
        if matches!(
            character,
            '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*'
        ) || character.is_control()
        {
            continue;
        }
        cleaned.push(character);
    }
    let cleaned = cleaned.trim_end_matches([' ', '.']);
    if cleaned.is_empty() {
        return Err(bad_params("文件名清理后为空"));
    }

    let lower = cleaned.to_ascii_lowercase();
    let (stem_raw, suffix) = if lower.ends_with(".exe") {
        let split = cleaned.len() - 4;
        (&cleaned[..split], &cleaned[split..])
    } else {
        (cleaned, ".exe")
    };
    let stem = stem_raw.trim_end_matches([' ', '.']);
    if stem.is_empty() {
        return Err(bad_params("文件名主体为空"));
    }
    if is_reserved_windows_name(stem) {
        return Err(bad_params("文件名是 Windows 保留名称"));
    }

    let mut result: String = stem.chars().take(116).collect();
    result.push_str(suffix);
    Ok(result)
}

fn is_reserved_windows_name(stem: &str) -> bool {
    let first = stem
        .split('.')
        .next()
        .unwrap_or(stem)
        .trim_end_matches([' ', '.']);
    let upper = first.to_ascii_uppercase();
    if matches!(upper.as_str(), "CON" | "PRN" | "AUX" | "NUL") {
        return true;
    }
    let bytes = upper.as_bytes();
    bytes.len() == 4
        && (upper.starts_with("COM") || upper.starts_with("LPT"))
        && (b'1'..=b'9').contains(&bytes[3])
}

fn unsafe_url(message: impl Into<String>) -> AppError {
    AppError::new(ErrorCode::UnsafeUrl, message)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::watchdog::{WatchdogAction, WatchdogConfig};
    use sha2::{Digest, Sha256};
    use std::net::{Shutdown, TcpListener, TcpStream};
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use std::sync::mpsc;
    use std::sync::Mutex;
    use std::thread;
    use tempfile::tempdir;
    use tiny_http::{Header, Response as StubResponse, Server};

    const MIB: usize = 1024 * 1024;

    #[derive(Default)]
    struct RecordingSink {
        events: Vec<Event>,
        responses: Vec<Response>,
        flushes: usize,
    }

    impl DownloadSink for RecordingSink {
        fn event(&mut self, event: &Event) -> io::Result<()> {
            self.events.push(event.clone());
            Ok(())
        }

        fn response(&mut self, response: &Response) -> io::Result<()> {
            self.responses.push(response.clone());
            self.flushes += 1;
            Ok(())
        }
    }

    struct RecordingAction {
        idle: AtomicUsize,
        aborts: AtomicUsize,
        socket: Arc<Mutex<Option<TcpStream>>>,
    }

    impl RecordingAction {
        fn new() -> Arc<Self> {
            Arc::new(Self {
                idle: AtomicUsize::new(0),
                aborts: AtomicUsize::new(0),
                socket: Arc::new(Mutex::new(None)),
            })
        }

        fn with_shared(socket: Arc<Mutex<Option<TcpStream>>>) -> Arc<Self> {
            Arc::new(Self {
                idle: AtomicUsize::new(0),
                aborts: AtomicUsize::new(0),
                socket,
            })
        }

        fn idle_count(&self) -> usize {
            self.idle.load(Ordering::SeqCst)
        }

        fn abort_count(&self) -> usize {
            self.aborts.load(Ordering::SeqCst)
        }
    }

    impl WatchdogAction for RecordingAction {
        fn on_idle_timeout(&self) {
            self.idle.fetch_add(1, Ordering::SeqCst);
            let deadline = Instant::now() + Duration::from_secs(2);
            loop {
                if let Ok(mut guard) = self.socket.lock() {
                    if let Some(socket) = guard.take() {
                        let _ = socket.shutdown(Shutdown::Both);
                        return;
                    }
                }
                if Instant::now() >= deadline {
                    return;
                }
                thread::sleep(Duration::from_millis(5));
            }
        }

        fn on_control_abort(&self) {
            self.aborts.fetch_add(1, Ordering::SeqCst);
        }
    }

    fn sample_bytes(size: usize) -> Vec<u8> {
        (0..size)
            .map(|index| ((index.wrapping_mul(31).wrapping_add(7)) % 251) as u8)
            .collect()
    }

    fn sha256_hex(bytes: &[u8]) -> String {
        Sha256::digest(bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect()
    }

    fn params_for(
        url: String,
        dest: &Path,
        data: &[u8],
        allow_insecure_localhost: bool,
    ) -> DownloadParams {
        DownloadParams {
            source_url: url,
            dest_path: dest.to_path_buf(),
            expected_sha256: sha256_hex(data),
            expected_size: data.len() as u64,
            allow_insecure_localhost,
        }
    }

    fn stub_server() -> (Server, std::net::SocketAddr) {
        let server = Server::http("127.0.0.1:0").expect("start stub");
        let addr = server.server_addr().to_ip().expect("loopback addr");
        (server, addr)
    }

    fn header_value(request: &tiny_http::Request, name: &'static str) -> Option<String> {
        request
            .headers()
            .iter()
            .find(|header| header.field.equiv(name))
            .map(|header| header.value.as_str().to_owned())
    }

    fn respond(
        request: tiny_http::Request,
        status: u16,
        body: Vec<u8>,
        headers: &[(&str, String)],
    ) {
        let mut response = StubResponse::from_data(body).with_status_code(status);
        for (name, value) in headers {
            response = response.with_header(
                Header::from_bytes(name.as_bytes(), value.as_bytes()).expect("stub header"),
            );
        }
        request.respond(response).expect("respond");
    }

    fn run_with(
        params: &DownloadParams,
        config: WatchdogConfig,
        action: Arc<dyn WatchdogAction>,
    ) -> (Result<DownloadReport, AppError>, RecordingSink) {
        run_with_id("dl-1", params, config, action)
    }

    fn run_with_id(
        id: &str,
        params: &DownloadParams,
        config: WatchdogConfig,
        action: Arc<dyn WatchdogAction>,
    ) -> (Result<DownloadReport, AppError>, RecordingSink) {
        let mut sink = RecordingSink::default();
        let result = execute_download(id, params, &mut sink, config, action);
        (result, sink)
    }

    fn default_config() -> WatchdogConfig {
        WatchdogConfig {
            idle_timeout_ms: 5_000,
            control_grace_ms: 1_500,
            poll_interval_ms: 10,
        }
    }

    fn progress_values(events: &[Event]) -> Vec<u64> {
        events
            .iter()
            .filter_map(|event| match event {
                Event::Progress { downloaded, .. } => Some(*downloaded),
                _ => None,
            })
            .collect()
    }

    fn state_values(events: &[Event]) -> Vec<DownloadState> {
        events
            .iter()
            .filter_map(|event| match event {
                Event::State { state, .. } => Some(*state),
                _ => None,
            })
            .collect()
    }

    fn failure_code(sink: &RecordingSink) -> Option<ErrorCode> {
        sink.responses
            .last()
            .and_then(|response| response.error.as_ref())
            .map(|error| error.code)
    }

    #[test]
    fn fresh_download_1mib_hashes_correctly_and_cleans_part_and_meta() {
        let data = sample_bytes(MIB);
        let body = data.clone();
        let (server, addr) = stub_server();
        let server_thread = thread::spawn(move || {
            let request = server.recv().expect("first request");
            assert_eq!(
                header_value(&request, "Accept-Encoding").as_deref(),
                Some("identity"),
                "every download request must pin identity encoding"
            );
            respond(request, 200, body, &[]);
        });

        let dir = tempdir().expect("tempdir");
        let dest = dir.path().join("FreeAssetFilter_Setup.exe");
        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);
        let action = RecordingAction::new();
        let (result, sink) = run_with(&params, default_config(), action.clone());
        server_thread.join().expect("server thread");

        let report = result.expect("download succeeds");
        assert_eq!(report.state, DownloadState::Done);
        assert_eq!(fs::read(&dest).expect("final file"), data);
        assert!(!state::part_path(&dest).exists(), "part renamed");
        assert!(!state::meta_path(&dest).exists(), "meta removed");
        assert_eq!(sink.flushes, 1, "terminal response flushed");
        assert_eq!(failure_code(&sink), None);
        assert_eq!(action.idle_count(), 0);

        let progress = progress_values(&sink.events);
        assert!(!progress.is_empty(), "at least one progress event");
        assert!(
            progress.windows(2).all(|pair| pair[0] <= pair[1]),
            "progress must be monotonic: {progress:?}"
        );
        assert_eq!(progress.last().copied(), Some(MIB as u64));
        assert_eq!(
            state_values(&sink.events).first().copied(),
            Some(DownloadState::Resolving)
        );
        assert_eq!(
            state_values(&sink.events).last().copied(),
            Some(DownloadState::Done)
        );
    }

    #[test]
    fn resume_with_seeded_part_sends_range_and_if_range_and_accepts_206() {
        let data = sample_bytes(MIB);
        let off = MIB / 4;
        let dir = tempdir().expect("tempdir");
        let dest = dir.path().join("FreeAssetFilter_Setup.exe");
        let (server, addr) = stub_server();
        let source = format!("http://{addr}/asset.exe");
        let params = params_for(source.clone(), &dest, &data, true);

        fs::write(state::part_path(&dest), &data[..off]).expect("seed part");
        state::write_meta(
            &state::meta_path(&dest),
            &PartMeta::new(
                source.clone(),
                Some("stub-etag".to_owned()),
                MIB as u64,
                params.expected_sha256.clone(),
                MIB as u64,
            ),
        )
        .expect("seed meta");

        let body = data[off..].to_vec();
        let (tx, rx) = mpsc::channel();
        let server_thread = thread::spawn(move || {
            let request = server.recv().expect("resume request");
            tx.send((
                header_value(&request, "Range"),
                header_value(&request, "If-Range"),
            ))
            .ok();
            respond(
                request,
                206,
                body,
                &[
                    ("Content-Range", format!("bytes {off}-{}/{}", MIB - 1, MIB)),
                    ("ETag", "stub-etag".to_owned()),
                ],
            );
        });

        let action = RecordingAction::new();
        let (result, sink) = run_with(&params, default_config(), action);
        server_thread.join().expect("server thread");

        let (range, if_range) = rx.recv_timeout(Duration::from_secs(5)).expect("headers");
        assert_eq!(range.as_deref(), Some(format!("bytes={off}-").as_str()));
        assert_eq!(if_range.as_deref(), Some("stub-etag"));
        let report = result.expect("resume succeeds");
        assert_eq!(report.downloaded, MIB as u64);
        assert_eq!(fs::read(&dest).expect("final file"), data);
        assert!(!state::meta_path(&dest).exists());
        assert_eq!(failure_code(&sink), None);
    }

    #[test]
    fn server_200_ignoring_range_restarts_from_zero() {
        let data = sample_bytes(MIB);
        let off = MIB / 4;
        let dir = tempdir().expect("tempdir");
        let dest = dir.path().join("FreeAssetFilter_Setup.exe");
        let (server, addr) = stub_server();
        let source = format!("http://{addr}/asset.exe");
        let params = params_for(source.clone(), &dest, &data, true);

        fs::write(state::part_path(&dest), &data[..off]).expect("seed part");
        state::write_meta(
            &state::meta_path(&dest),
            &PartMeta::new(
                source,
                None,
                MIB as u64,
                params.expected_sha256.clone(),
                MIB as u64,
            ),
        )
        .expect("seed meta");

        let body = data.clone();
        let (tx, rx) = mpsc::channel();
        let server_thread = thread::spawn(move || {
            let request = server.recv().expect("request");
            tx.send(header_value(&request, "Range")).ok();
            respond(request, 200, body, &[]);
        });

        let action = RecordingAction::new();
        let (result, _) = run_with(&params, default_config(), action);
        server_thread.join().expect("server thread");

        assert_eq!(
            rx.recv_timeout(Duration::from_secs(5)).expect("header"),
            Some(format!("bytes={off}-"))
        );
        result.expect("200 restart succeeds");
        assert_eq!(fs::read(&dest).expect("final file"), data);
        assert!(!state::part_path(&dest).exists());
    }

    #[test]
    fn wrong_206_start_is_truncated_and_restarted_once() {
        let data = sample_bytes(MIB);
        let off = MIB / 4;
        let dir = tempdir().expect("tempdir");
        let dest = dir.path().join("FreeAssetFilter_Setup.exe");
        let (server, addr) = stub_server();
        let source = format!("http://{addr}/asset.exe");
        let params = params_for(source.clone(), &dest, &data, true);

        fs::write(state::part_path(&dest), &data[..off]).expect("seed part");
        state::write_meta(
            &state::meta_path(&dest),
            &PartMeta::new(
                source,
                None,
                MIB as u64,
                params.expected_sha256.clone(),
                MIB as u64,
            ),
        )
        .expect("seed meta");

        let body_bad = data[100..].to_vec();
        let body_full = data.clone();
        let (tx, rx) = mpsc::channel();
        let server_thread = thread::spawn(move || {
            let first = server.recv().expect("first request");
            tx.send(header_value(&first, "Range")).ok();
            respond(
                first,
                206,
                body_bad,
                &[("Content-Range", format!("bytes 100-{}/{}", MIB - 1, MIB))],
            );

            let second = server.recv().expect("second request");
            tx.send(header_value(&second, "Range")).ok();
            respond(second, 200, body_full, &[]);
        });

        let action = RecordingAction::new();
        let (result, _) = run_with(&params, default_config(), action);
        server_thread.join().expect("server thread");

        let first_range = rx.recv_timeout(Duration::from_secs(5)).expect("first");
        let second_range = rx.recv_timeout(Duration::from_secs(5)).expect("second");
        assert_eq!(first_range, Some(format!("bytes={off}-")));
        assert_eq!(second_range, None, "restart must not ask for a range");
        result.expect("restart recovers");
        assert_eq!(fs::read(&dest).expect("final file"), data);
    }

    #[test]
    fn status_416_transitions_to_verification_without_corrupt_final_file() {
        let data = sample_bytes(MIB);
        let dir = tempdir().expect("tempdir");
        let dest = dir.path().join("FreeAssetFilter_Setup.exe");
        let (server, addr) = stub_server();
        let source = format!("http://{addr}/asset.exe");
        let params = params_for(source.clone(), &dest, &data, true);

        fs::write(state::part_path(&dest), &data).expect("seed full part");
        state::write_meta(
            &state::meta_path(&dest),
            &PartMeta::new(
                source,
                None,
                MIB as u64,
                params.expected_sha256.clone(),
                MIB as u64,
            ),
        )
        .expect("seed meta");

        let server_thread = thread::spawn(move || {
            let request = server.recv().expect("request");
            respond(
                request,
                416,
                Vec::new(),
                &[("Content-Range", format!("bytes */{MIB}"))],
            );
        });

        let action = RecordingAction::new();
        let (result, sink) = run_with(&params, default_config(), action);
        server_thread.join().expect("server thread");

        result.expect("416 goes to verification");
        assert_eq!(fs::read(&dest).expect("final file"), data);
        assert!(!state::part_path(&dest).exists());
        assert!(!state::meta_path(&dest).exists());
        assert!(
            state_values(&sink.events).contains(&DownloadState::Verifying),
            "416 must enter the verification state"
        );
    }

    #[test]
    fn download_url_rules_reject_unsafe_hosts_and_schemes() {
        let unsafe_cases = [
            "https://evil.example/x.exe",
            "https://github.com.evil.com/x.exe",
            "https://api.github.com.evil.com/x.exe",
            "https://evilgithubusercontent.com/x.exe",
            "https://user:pass@github.com/x.exe",
            "https://github.com:8443/x.exe",
            "https://127.0.0.1/x.exe",
        ];
        for raw in unsafe_cases {
            let error = validate_download_url(raw, false).expect_err(raw);
            assert_eq!(error.code, ErrorCode::UnsafeUrl, "{raw}");
        }

        assert!(validate_download_url("https://github.com/x.exe", false).is_ok());
        assert!(validate_download_url("https://api.github.com/x", false).is_ok());
        assert!(validate_download_url("https://objects.githubusercontent.com/x", false).is_ok());
        assert!(
            validate_download_url("https://release-assets.githubusercontent.com/x", false).is_ok()
        );

        let error = validate_download_url("http://127.0.0.1:8080/x.exe", false).expect_err("http");
        assert_eq!(error.code, ErrorCode::UnsafeUrl);
        assert!(validate_download_url("http://127.0.0.1:8080/x.exe", true).is_ok());
        assert!(validate_download_url("http://127.0.0.1:54321/x.exe", true).is_ok());
        assert!(validate_download_url("http://[::1]:9/x.exe", true).is_ok());
        assert!(validate_download_url("http://localhost:8080/x.exe", true).is_err());
    }

    #[test]
    fn redirect_resolution_uses_base_join_and_revalidates_each_hop() {
        let base = Url::parse("http://127.0.0.1:1234/a/b.exe").expect("base");

        let relative = resolve_redirect(&base, "payload.exe", true).expect("relative");
        assert_eq!(relative.as_str(), "http://127.0.0.1:1234/a/payload.exe");

        let root_relative = resolve_redirect(&base, "/root.exe", true).expect("root relative");
        assert_eq!(root_relative.as_str(), "http://127.0.0.1:1234/root.exe");

        let evil = resolve_redirect(&base, "https://evil.example/x.exe", true)
            .expect_err("evil hop must be rejected");
        assert_eq!(evil.code, ErrorCode::UnsafeUrl);

        let bad_relative =
            resolve_redirect(&base, "http://127.0.0.1:1234/x.exe", false).expect_err("no flag");
        assert_eq!(bad_relative.code, ErrorCode::UnsafeUrl);
    }

    #[test]
    fn redirect_chain_to_evil_host_is_rejected_after_valid_first_hop() {
        let data = sample_bytes(MIB);
        let dir = tempdir().expect("tempdir");
        let dest = dir.path().join("FreeAssetFilter_Setup.exe");
        let (server, addr) = stub_server();
        let params = params_for(format!("http://{addr}/start.exe"), &dest, &data, true);

        let server_thread = thread::spawn(move || {
            let request = server.recv().expect("first hop");
            respond(
                request,
                302,
                Vec::new(),
                &[("Location", "https://evil.example/x.exe".to_owned())],
            );
        });

        let action = RecordingAction::new();
        let (result, sink) = run_with(&params, default_config(), action);
        server_thread.join().expect("server thread");

        let error = result.expect_err("evil redirect");
        assert_eq!(error.code, ErrorCode::UnsafeUrl);
        assert_eq!(failure_code(&sink), Some(ErrorCode::UnsafeUrl));
        assert!(!dest.exists(), "no final file for rejected redirect");
    }

    #[test]
    fn relative_redirect_location_is_joined_and_downloaded() {
        let data = sample_bytes(MIB);
        let dir = tempdir().expect("tempdir");
        let dest = dir.path().join("FreeAssetFilter_Setup.exe");
        let (server, addr) = stub_server();
        let params = params_for(format!("http://{addr}/start.exe"), &dest, &data, true);

        let body = data.clone();
        let server_thread = thread::spawn(move || {
            let first = server.recv().expect("first");
            respond(
                first,
                302,
                Vec::new(),
                &[("Location", "payload.exe".to_owned())],
            );
            let second = server.recv().expect("second");
            respond(second, 200, body, &[]);
        });

        let action = RecordingAction::new();
        let (result, _) = run_with(&params, default_config(), action);
        server_thread.join().expect("server thread");

        result.expect("relative redirect succeeds");
        assert_eq!(fs::read(&dest).expect("final file"), data);
    }

    #[test]
    fn ipv6_loopback_downloads_when_flag_is_set() {
        let server = match Server::http("[::1]:0") {
            Ok(server) => server,
            Err(error) => panic!("IPv6 loopback stub required: {error}"),
        };
        let addr = server.server_addr().to_ip().expect("ipv6 addr");
        assert!(addr.is_ipv6());

        let data = sample_bytes(MIB);
        let body = data.clone();
        let server_thread = thread::spawn(move || {
            let request = server.recv().expect("request");
            respond(request, 200, body, &[]);
        });

        let dir = tempdir().expect("tempdir");
        let dest = dir.path().join("FreeAssetFilter_Setup.exe");
        let params = params_for(
            format!("http://[::1]:{}/asset.exe", addr.port()),
            &dest,
            &data,
            true,
        );
        let action = RecordingAction::new();
        let (result, _) = run_with(&params, default_config(), action);
        server_thread.join().expect("server thread");

        result.expect("ipv6 loopback download");
        assert_eq!(fs::read(&dest).expect("final file"), data);
    }

    #[test]
    fn slow_redirect_hops_refresh_progress_and_do_not_trigger_watchdog() {
        let data = sample_bytes(MIB);
        let dir = tempdir().expect("tempdir");
        let dest = dir.path().join("FreeAssetFilter_Setup.exe");
        let (server, addr) = stub_server();
        let params = params_for(format!("http://{addr}/hop0"), &dest, &data, true);

        let body = data.clone();
        let server_thread = thread::spawn(move || {
            for hop in 0..5 {
                let request = server.recv().expect("hop request");
                thread::sleep(Duration::from_millis(180));
                if hop < 4 {
                    respond(
                        request,
                        302,
                        Vec::new(),
                        &[("Location", format!("/hop{}", hop + 1))],
                    );
                } else {
                    respond(request, 200, body.clone(), &[]);
                }
            }
        });

        let config = WatchdogConfig {
            idle_timeout_ms: 300,
            control_grace_ms: 1_500,
            poll_interval_ms: 10,
        };
        let action = RecordingAction::new();
        let started = Instant::now();
        let (result, _) = run_with(&params, config, action.clone());
        let elapsed = started.elapsed();
        server_thread.join().expect("server thread");

        result.expect("slow redirects must succeed");
        assert!(
            elapsed > Duration::from_millis(300),
            "test must exceed the idle threshold in total ({elapsed:?})"
        );
        assert_eq!(
            action.idle_count(),
            0,
            "each hop must refresh last_progress_ms"
        );
        assert_eq!(fs::read(&dest).expect("final file"), data);
    }

    #[test]
    fn expected_size_is_required_and_bounded() {
        let dir = tempdir().expect("tempdir");
        let dest = dir.path().join("FreeAssetFilter_Setup.exe");
        let base = |size: Value| {
            json!({
                "source_url": "https://github.com/x.exe",
                "dest_path": dest.to_string_lossy(),
                "expected_sha256": "a".repeat(64),
                "expected_size": size,
                "allow_insecure_localhost": false
            })
        };

        for value in [
            Value::Null,
            json!(0),
            json!(MIN_EXPECTED_SIZE - 1),
            json!(MAX_EXPECTED_SIZE + 1),
        ] {
            let error = DownloadParams::from_value(&base(value.clone()))
                .expect_err(&format!("size {value} must be rejected"));
            assert_eq!(error.code, ErrorCode::BadParams, "size {value}");
        }

        let params = DownloadParams::from_value(&base(json!(MIN_EXPECTED_SIZE)))
            .expect("1 MiB is the lower bound");
        assert_eq!(params.expected_size, MIN_EXPECTED_SIZE);

        let params = DownloadParams::from_value(&base(json!(MAX_EXPECTED_SIZE)))
            .expect("2 GiB is the upper bound");
        assert_eq!(params.expected_size, MAX_EXPECTED_SIZE);
    }

    #[test]
    fn expected_sha256_missing_or_malformed_is_bad_params() {
        let dir = tempdir().expect("tempdir");
        let dest = dir.path().join("FreeAssetFilter_Setup.exe");
        let mut value = json!({
            "source_url": "https://github.com/x.exe",
            "dest_path": dest.to_string_lossy(),
            "expected_sha256": Value::Null,
            "expected_size": MIN_EXPECTED_SIZE,
            "allow_insecure_localhost": false
        });
        let error = DownloadParams::from_value(&value).expect_err("null sha");
        assert_eq!(error.code, ErrorCode::BadParams);

        value["expected_sha256"] = json!("abc");
        let error = DownloadParams::from_value(&value).expect_err("short sha");
        assert_eq!(error.code, ErrorCode::BadParams);
    }

    #[test]
    fn timeout_writes_timeout_response_keeps_part_and_never_exits_process() {
        let data = sample_bytes(MIB);
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind stall stub");
        let addr = listener.local_addr().expect("addr");
        let first_chunk = data[..4096].to_vec();
        let socket_slot: Arc<Mutex<Option<TcpStream>>> = Arc::new(Mutex::new(None));
        let server_slot = Arc::clone(&socket_slot);
        let server_thread = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            let mut buffer = [0u8; 8192];
            let _ = stream.read(&mut buffer).expect("request bytes");
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 1048576\r\n\r\n")
                .expect("headers");
            stream.write_all(&first_chunk).expect("first bytes");
            stream.flush().expect("flush");
            *server_slot.lock().expect("socket slot") = Some(stream.try_clone().expect("clone"));
            let mut sink = [0u8; 1024];
            loop {
                match stream.read(&mut sink) {
                    Ok(0) | Err(_) => break,
                    Ok(_) => {}
                }
            }
        });

        let dir = tempdir().expect("tempdir");
        let dest = dir.path().join("FreeAssetFilter_Setup.exe");
        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);

        let config = WatchdogConfig {
            idle_timeout_ms: 200,
            control_grace_ms: 1_500,
            poll_interval_ms: 10,
        };
        let action = RecordingAction::with_shared(Arc::clone(&socket_slot));
        let (result, sink) = run_with(&params, config, action.clone());
        server_thread.join().expect("server thread");

        let error = result.expect_err("stall times out");
        assert_eq!(error.code, ErrorCode::Timeout);
        assert_eq!(failure_code(&sink), Some(ErrorCode::Timeout));
        assert_eq!(sink.flushes, 1, "timeout response must be flushed");
        assert_eq!(action.idle_count(), 1, "idle action fires exactly once");
        assert_eq!(action.abort_count(), 0);
        assert!(!dest.exists(), "no final file on timeout");
        let part = state::part_path(&dest);
        let retained = fs::read(&part).expect("part preserved for resume");
        assert!(!retained.is_empty(), "retained part carries received bytes");
        assert!(
            state::meta_path(&dest).exists(),
            "meta preserved for resume"
        );
    }

    #[test]
    fn non_identity_content_encoding_is_rejected_before_writing() {
        let data = sample_bytes(MIB);
        let body = data.clone();
        let (server, addr) = stub_server();
        let server_thread = thread::spawn(move || {
            let request = server.recv().expect("request");
            respond(
                request,
                200,
                body,
                &[("Content-Encoding", "gzip".to_owned())],
            );
        });

        let dir = tempdir().expect("tempdir");
        let dest = dir.path().join("FreeAssetFilter_Setup.exe");
        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);
        let action = RecordingAction::new();
        let (result, sink) = run_with(&params, default_config(), action);
        server_thread.join().expect("server thread");

        let error = result.expect_err("compressed transfer must be rejected");
        assert!(
            matches!(error.code, ErrorCode::HttpStatus | ErrorCode::BadRange),
            "unexpected code: {error:?}"
        );
        assert_eq!(failure_code(&sink), Some(error.code));
        assert!(!dest.exists(), "no final file");
        assert!(!state::part_path(&dest).exists(), "no corrupted part");
    }

    #[test]
    fn sanitize_matches_shared_cross_language_fixture() {
        #[derive(serde::Deserialize)]
        struct Fixture {
            schema: u32,
            cases: Vec<Case>,
        }

        #[derive(serde::Deserialize)]
        struct Case {
            input: String,
            expected: Option<String>,
            note: String,
        }

        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../../../tests/fixtures/asset_names.json");
        let raw = fs::read_to_string(&path).unwrap_or_else(|error| {
            panic!(
                "shared asset-name fixture missing at {}: {error}",
                path.display()
            )
        });
        let fixture: Fixture = serde_json::from_str(&raw).expect("fixture JSON");
        assert_eq!(fixture.schema, 1);
        assert_eq!(fixture.cases.len(), 21);

        for case in fixture.cases {
            match case.expected {
                Some(expected) => {
                    let actual = sanitize_asset_name(&case.input)
                        .unwrap_or_else(|error| panic!("{}: {error}", case.note));
                    assert_eq!(actual, expected, "{}", case.note);
                }
                None => {
                    let error = sanitize_asset_name(&case.input)
                        .expect_err(&format!("{} must be rejected", case.note));
                    assert_eq!(error.code, ErrorCode::BadParams, "{}", case.note);
                }
            }
        }
    }

    // -----------------------------------------------------------------------
    // pause / cancel / busy gate / retry / verification / cleanup coverage.

    struct HookSink<'a> {
        inner: RecordingSink,
        hook: &'a mut dyn FnMut(&Event),
    }

    impl DownloadSink for HookSink<'_> {
        fn event(&mut self, event: &Event) -> io::Result<()> {
            (self.hook)(event);
            self.inner.event(event)
        }

        fn response(&mut self, response: &Response) -> io::Result<()> {
            self.inner.response(response)
        }
    }

    fn run_controlled(
        params: &DownloadParams,
        control: &DownloadControl,
        runtime: &DownloadRuntime,
        hook: &mut dyn FnMut(&Event),
    ) -> (Result<DownloadReport, AppError>, RecordingSink) {
        let mut sink = HookSink {
            inner: RecordingSink::default(),
            hook,
        };
        let result = execute_download_with_control("dl-1", params, &mut sink, control, runtime);
        (result, sink.inner)
    }

    fn fast_retry() -> RetryPolicy {
        RetryPolicy {
            max_attempts: 3,
            backoff: vec![Duration::from_millis(10), Duration::from_millis(20)],
        }
    }

    fn runtime_with(
        config: WatchdogConfig,
        action: Arc<dyn WatchdogAction>,
        retry: RetryPolicy,
        gate: Arc<dyn DownloadGate>,
    ) -> DownloadRuntime {
        DownloadRuntime {
            watchdog_config: config,
            watchdog_action: action,
            retry,
            gate,
        }
    }

    /// Serves `body` in `chunk`-sized pieces with a sleep between writes.
    fn paced_server(
        body: Vec<u8>,
        chunk: usize,
        delay: Duration,
    ) -> (std::net::SocketAddr, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind paced stub");
        let addr = listener.local_addr().expect("addr");
        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            let mut request = Vec::new();
            let mut byte = [0u8; 1024];
            loop {
                match stream.read(&mut byte) {
                    Ok(0) | Err(_) => break,
                    Ok(read) => {
                        request.extend_from_slice(&byte[..read]);
                        if request.windows(4).any(|window| window == b"\r\n\r\n") {
                            break;
                        }
                    }
                }
            }
            let head = format!(
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            );
            if stream.write_all(head.as_bytes()).is_err() {
                return;
            }
            for piece in body.chunks(chunk.max(1)) {
                if stream.write_all(piece).is_err() {
                    return;
                }
                let _ = stream.flush();
                thread::sleep(delay);
            }
        });
        (addr, handle)
    }

    /// Accepts up to `expected` connections and closes each one immediately.
    fn drop_server(
        expected: usize,
    ) -> (
        std::net::SocketAddr,
        Arc<AtomicUsize>,
        Arc<AtomicBool>,
        thread::JoinHandle<()>,
    ) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind drop stub");
        listener.set_nonblocking(true).expect("nonblocking");
        let addr = listener.local_addr().expect("addr");
        let count = Arc::new(AtomicUsize::new(0));
        let stop = Arc::new(AtomicBool::new(false));
        let counter = Arc::clone(&count);
        let stopper = Arc::clone(&stop);
        let handle = thread::spawn(move || {
            while counter.load(Ordering::SeqCst) < expected && !stopper.load(Ordering::SeqCst) {
                match listener.accept() {
                    Ok((stream, _)) => {
                        counter.fetch_add(1, Ordering::SeqCst);
                        drop(stream);
                    }
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(2));
                    }
                    Err(_) => break,
                }
            }
        });
        (addr, count, stop, handle)
    }

    fn seeded_dest(dir: &tempfile::TempDir) -> PathBuf {
        let dest = dir.path().join("FreeAssetFilter_Setup.exe");
        fs::create_dir_all(dir.path()).expect("dir");
        dest
    }

    #[test]
    fn pause_before_start_returns_paused_without_touching_the_network() {
        let dir = tempdir().expect("tempdir");
        let dest = seeded_dest(&dir);
        let data = sample_bytes(64 * 1024);
        // Port 9 is never contacted: the pre-start control check returns first.
        let params = params_for(
            "http://127.0.0.1:9/asset.exe".to_owned(),
            &dest,
            &data,
            true,
        );

        let control = DownloadControl::new();
        assert!(control.request_pause());
        let runtime = DownloadRuntime::isolated(default_config(), RecordingAction::new());
        let (result, sink) = run_controlled(&params, &control, &runtime, &mut |_| {});

        let report = result.expect("a pre-start pause is not an error");
        assert_eq!(report.state, DownloadState::Paused);
        assert_eq!(report.sha256, None);
        assert_eq!(report.downloaded, 0);
        assert_eq!(state_values(&sink.events), vec![DownloadState::Paused]);
        assert_eq!(sink.flushes, 1, "paused response must be flushed");
        assert!(!state::part_path(&dest).exists());
        assert!(!dest.exists());
    }

    #[test]
    fn cancel_before_start_removes_seeded_part_and_meta() {
        let dir = tempdir().expect("tempdir");
        let data = sample_bytes(64 * 1024);
        let dest = seeded_dest(&dir);
        let part = state::part_path(&dest);
        let meta = state::meta_path(&dest);
        fs::write(&part, &data[..4096]).expect("seed part");
        state::write_meta(
            &meta,
            &PartMeta::new(
                "http://127.0.0.1:9/asset.exe".to_owned(),
                None,
                data.len() as u64,
                sha256_hex(&data),
                data.len() as u64,
            ),
        )
        .expect("seed meta");

        let params = params_for(
            "http://127.0.0.1:9/asset.exe".to_owned(),
            &dest,
            &data,
            true,
        );
        let control = DownloadControl::new();
        assert!(control.request_cancel());
        let runtime = DownloadRuntime::isolated(default_config(), RecordingAction::new());
        let (result, sink) = run_controlled(&params, &control, &runtime, &mut |_| {});

        let report = result.expect("a pre-start cancel is not an error");
        assert_eq!(report.state, DownloadState::Cancelled);
        assert_eq!(report.sha256, None);
        assert_eq!(state_values(&sink.events), vec![DownloadState::Cancelled]);
        assert!(!part.exists(), "part removed on cancel");
        assert!(!meta.exists(), "meta removed on cancel");
        assert!(!dest.exists());
    }

    #[test]
    fn pause_mid_transfer_keeps_part_and_meta_for_resume() {
        let data = sample_bytes(512 * 1024);
        let (addr, server) = paced_server(data.clone(), 16 * 1024, Duration::from_millis(10));
        let dir = tempdir().expect("tempdir");
        let dest = seeded_dest(&dir);
        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);

        let control = DownloadControl::new();
        let runtime = DownloadRuntime::isolated(default_config(), RecordingAction::new());
        let (result, sink) = run_controlled(&params, &control, &runtime, &mut |event| {
            if let Event::Progress { downloaded, .. } = event {
                if *downloaded >= 128 * 1024 {
                    control.request_pause();
                }
            }
        });
        server.join().expect("server thread");

        let report = result.expect("pause is not an error");
        assert_eq!(report.state, DownloadState::Paused);
        assert_eq!(report.sha256, None);
        let part = state::part_path(&dest);
        let kept = fs::metadata(&part).expect("part kept").len();
        assert!(kept >= 128 * 1024, "kept bytes: {kept}");
        assert!(kept < data.len() as u64, "pause stops before completion");
        assert!(state::meta_path(&dest).exists(), "meta kept for resume");
        assert!(!dest.exists(), "no final file while paused");
        assert_eq!(
            state_values(&sink.events).last().copied(),
            Some(DownloadState::Paused)
        );
        assert_eq!(sink.flushes, 1);
    }

    #[test]
    fn cancel_mid_transfer_removes_part_and_meta() {
        let data = sample_bytes(512 * 1024);
        let (addr, server) = paced_server(data.clone(), 16 * 1024, Duration::from_millis(10));
        let dir = tempdir().expect("tempdir");
        let dest = seeded_dest(&dir);
        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);

        let control = DownloadControl::new();
        let runtime = DownloadRuntime::isolated(default_config(), RecordingAction::new());
        let (result, _sink) = run_controlled(&params, &control, &runtime, &mut |event| {
            if let Event::Progress { downloaded, .. } = event {
                if *downloaded >= 64 * 1024 {
                    control.request_cancel();
                }
            }
        });
        server.join().expect("server thread");

        let report = result.expect("cancel is not an error");
        assert_eq!(report.state, DownloadState::Cancelled);
        assert_eq!(report.sha256, None);
        assert!(!state::part_path(&dest).exists(), "part removed");
        assert!(!state::meta_path(&dest).exists(), "meta removed");
        assert!(!dest.exists());
    }

    #[test]
    fn mid_body_disconnect_keeps_part_and_never_retries() {
        let data = sample_bytes(512 * 1024);
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind stub");
        let addr = listener.local_addr().expect("addr");
        let accepted = Arc::new(AtomicUsize::new(0));
        let counter = Arc::clone(&accepted);
        let head = format!(
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            data.len()
        );
        let first = data[..64 * 1024].to_vec();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            counter.fetch_add(1, Ordering::SeqCst);
            let mut request = [0u8; 4096];
            let _ = stream.read(&mut request);
            stream.write_all(head.as_bytes()).expect("headers");
            stream.write_all(&first).expect("first bytes");
            stream.flush().expect("flush");
            // Let the client consume the bytes, then close mid-body. A retry
            // would land in the backlog and be rejected by the guard loop.
            listener.set_nonblocking(true).ok();
            for _ in 0..30 {
                match listener.accept() {
                    Ok((extra, _)) => {
                        counter.fetch_add(1, Ordering::SeqCst);
                        drop(extra);
                    }
                    Err(_) => thread::sleep(Duration::from_millis(10)),
                }
            }
        });

        let dir = tempdir().expect("tempdir");
        let dest = seeded_dest(&dir);
        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);
        let runtime = runtime_with(
            default_config(),
            RecordingAction::new(),
            fast_retry(),
            Arc::new(ExclusiveDownloadGate::new()),
        );
        let (result, sink) =
            run_controlled(&params, &DownloadControl::new(), &runtime, &mut |_| {});
        server.join().expect("server thread");

        let error = result.expect_err("a truncated body is a network error");
        assert_eq!(error.code, ErrorCode::Network);
        assert_eq!(failure_code(&sink), Some(ErrorCode::Network));
        assert_eq!(accepted.load(Ordering::SeqCst), 1, "no retry after bytes");
        let part = state::part_path(&dest);
        assert!(part.exists(), "partial bytes kept for resume");
        assert!(fs::metadata(&part).expect("part").len() > 0);
        assert!(state::meta_path(&dest).exists());
        assert!(!dest.exists());
    }

    #[test]
    fn pre_byte_network_failures_retry_three_times_then_fail() {
        let (addr, count, stop, server) = drop_server(3);
        let data = sample_bytes(64 * 1024);
        let dir = tempdir().expect("tempdir");
        let dest = seeded_dest(&dir);
        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);
        let runtime = runtime_with(
            default_config(),
            RecordingAction::new(),
            fast_retry(),
            Arc::new(ExclusiveDownloadGate::new()),
        );

        let (result, sink) =
            run_controlled(&params, &DownloadControl::new(), &runtime, &mut |_| {});
        stop.store(true, Ordering::SeqCst);
        server.join().expect("server thread");

        let error = result.expect_err("all attempts fail");
        assert_eq!(error.code, ErrorCode::Network);
        assert_eq!(failure_code(&sink), Some(ErrorCode::Network));
        assert_eq!(sink.flushes, 1, "only the terminal response is written");
        assert_eq!(count.load(Ordering::SeqCst), 3, "exactly three attempts");
        assert!(!state::part_path(&dest).exists());
        assert!(!dest.exists());
    }

    #[test]
    fn http_5xx_before_first_byte_is_retried_then_surfaces() {
        let (server, addr) = stub_server();
        let seen = Arc::new(AtomicUsize::new(0));
        let counter = Arc::clone(&seen);
        let server_thread = thread::spawn(move || {
            if let Ok(Some(request)) = server.recv_timeout(Duration::from_secs(5)) {
                counter.fetch_add(1, Ordering::SeqCst);
                respond(request, 500, Vec::new(), &[]);
            }
            for _ in 0..2 {
                match server.recv_timeout(Duration::from_secs(5)) {
                    Ok(Some(request)) => {
                        counter.fetch_add(1, Ordering::SeqCst);
                        respond(request, 500, Vec::new(), &[]);
                    }
                    _ => break,
                }
            }
        });

        let data = sample_bytes(64 * 1024);
        let dir = tempdir().expect("tempdir");
        let dest = seeded_dest(&dir);
        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);
        let runtime = runtime_with(
            default_config(),
            RecordingAction::new(),
            fast_retry(),
            Arc::new(ExclusiveDownloadGate::new()),
        );

        let (result, _sink) =
            run_controlled(&params, &DownloadControl::new(), &runtime, &mut |_| {});
        server_thread.join().expect("server thread");

        let error = result.expect_err("5xx exhausts retries");
        assert_eq!(error.code, ErrorCode::HttpStatus);
        assert_eq!(seen.load(Ordering::SeqCst), 3);
        assert!(!state::part_path(&dest).exists());
    }

    #[test]
    fn http_4xx_is_not_retried() {
        let (server, addr) = stub_server();
        let seen = Arc::new(AtomicUsize::new(0));
        let counter = Arc::clone(&seen);
        let stop = Arc::new(AtomicBool::new(false));
        let stopper = Arc::clone(&stop);
        let server_thread = thread::spawn(move || {
            while !stopper.load(Ordering::SeqCst) {
                match server.recv_timeout(Duration::from_millis(100)) {
                    Ok(Some(request)) => {
                        counter.fetch_add(1, Ordering::SeqCst);
                        respond(request, 404, Vec::new(), &[]);
                    }
                    Ok(None) => {}
                    Err(_) => break,
                }
            }
        });

        let data = sample_bytes(64 * 1024);
        let dir = tempdir().expect("tempdir");
        let dest = seeded_dest(&dir);
        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);
        let runtime = runtime_with(
            default_config(),
            RecordingAction::new(),
            fast_retry(),
            Arc::new(ExclusiveDownloadGate::new()),
        );

        let (result, _sink) =
            run_controlled(&params, &DownloadControl::new(), &runtime, &mut |_| {});
        stop.store(true, Ordering::SeqCst);
        server_thread.join().expect("server thread");

        let error = result.expect_err("404 surfaces");
        assert_eq!(error.code, ErrorCode::HttpStatus);
        assert_eq!(seen.load(Ordering::SeqCst), 1, "4xx must not retry");
    }

    #[test]
    fn second_download_across_threads_is_rejected_as_busy() {
        let data = sample_bytes(256 * 1024);
        let (addr, server) = paced_server(data.clone(), 8 * 1024, Duration::from_millis(10));
        let dir = tempdir().expect("tempdir");
        let dest = seeded_dest(&dir);
        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);

        let gate: Arc<dyn DownloadGate> = Arc::new(ExclusiveDownloadGate::new());
        let (started_tx, started_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();

        let first_params = params.clone();
        let first_runtime = runtime_with(
            default_config(),
            RecordingAction::new(),
            RetryPolicy::immediate(),
            Arc::clone(&gate),
        );
        let first = thread::spawn(move || {
            let control = DownloadControl::new();
            let mut released = false;
            let mut hook = |event: &Event| {
                if released {
                    return;
                }
                if let Event::Progress { .. } = event {
                    released = true;
                    started_tx.send(()).ok();
                    release_rx.recv_timeout(Duration::from_secs(10)).ok();
                }
            };
            run_controlled(&first_params, &control, &first_runtime, &mut hook)
        });

        started_rx
            .recv_timeout(Duration::from_secs(10))
            .expect("first download must start");
        let second_runtime = runtime_with(
            default_config(),
            RecordingAction::new(),
            RetryPolicy::immediate(),
            Arc::clone(&gate),
        );
        let (second, second_sink) = run_controlled(
            &params,
            &DownloadControl::new(),
            &second_runtime,
            &mut |_| {},
        );
        let busy = second.expect_err("second download must be rejected");
        assert_eq!(busy.code, ErrorCode::Busy);
        assert_eq!(failure_code(&second_sink), Some(ErrorCode::Busy));
        assert_eq!(second_sink.flushes, 1);

        release_tx.send(()).ok();
        let (first_result, _) = first.join().expect("first download thread");
        server.join().expect("server thread");
        assert_eq!(
            first_result.expect("first download completes").state,
            DownloadState::Done
        );
    }

    #[test]
    fn pause_is_rejected_while_verifying() {
        let data = sample_bytes(256 * 1024);
        let body = data.clone();
        let (server, addr) = stub_server();
        let server_thread = thread::spawn(move || {
            if let Ok(request) = server.recv() {
                respond(request, 200, body, &[]);
            }
        });

        let dir = tempdir().expect("tempdir");
        let dest = seeded_dest(&dir);
        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);
        let control = DownloadControl::new();
        let runtime = DownloadRuntime::isolated(default_config(), RecordingAction::new());
        let (result, _sink) = run_controlled(&params, &control, &runtime, &mut |event| {
            if let Event::State { state, .. } = event {
                if *state == DownloadState::Verifying {
                    assert!(
                        control.is_verifying(),
                        "verifying flag must be visible with the state event"
                    );
                    assert!(
                        !control.request_pause(),
                        "pause must be rejected during verification"
                    );
                }
            }
        });
        server_thread.join().expect("server thread");

        assert_eq!(
            result.expect("download completes").state,
            DownloadState::Done
        );
        assert!(!control.is_verifying(), "flag cleared after terminal state");
    }

    #[test]
    fn cancel_during_verifying_removes_every_artifact() {
        let data = sample_bytes(MIB);
        let body = data.clone();
        let (server, addr) = stub_server();
        let server_thread = thread::spawn(move || {
            if let Ok(request) = server.recv() {
                respond(request, 200, body, &[]);
            }
        });

        let dir = tempdir().expect("tempdir");
        let dest = seeded_dest(&dir);
        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);
        let control = DownloadControl::new();
        let runtime = DownloadRuntime::isolated(default_config(), RecordingAction::new());
        let (result, _sink) = run_controlled(&params, &control, &runtime, &mut |event| {
            if let Event::State { state, .. } = event {
                if *state == DownloadState::Verifying {
                    assert!(control.request_cancel());
                }
            }
        });
        server_thread.join().expect("server thread");

        let report = result.expect("cancel during verification is not an error");
        assert_eq!(report.state, DownloadState::Cancelled);
        assert_eq!(report.sha256, None);
        assert!(!dest.exists(), "final file removed");
        assert!(!state::part_path(&dest).exists());
        assert!(!state::meta_path(&dest).exists());
    }

    #[test]
    fn checksum_mismatch_removes_artifacts_and_a_correct_retry_succeeds() {
        let data = sample_bytes(128 * 1024);
        let mut tampered = data.clone();
        tampered[0] ^= 0xff;
        let body = tampered.clone();
        let (server, addr) = stub_server();
        let server_thread = thread::spawn(move || {
            if let Ok(request) = server.recv() {
                respond(request, 200, body, &[]);
            }
        });

        let dir = tempdir().expect("tempdir");
        let dest = seeded_dest(&dir);
        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);
        let runtime = DownloadRuntime::isolated(default_config(), RecordingAction::new());
        let (result, sink) =
            run_controlled(&params, &DownloadControl::new(), &runtime, &mut |_| {});
        server_thread.join().expect("server thread");

        let error = result.expect_err("wrong bytes must fail verification");
        assert_eq!(error.code, ErrorCode::ChecksumMismatch);
        assert_eq!(failure_code(&sink), Some(ErrorCode::ChecksumMismatch));
        assert!(error.message.contains("校验失败"));
        assert!(!state::part_path(&dest).exists());
        assert!(!state::meta_path(&dest).exists());
        assert!(!dest.exists());

        // A retry with the right bytes must succeed and leave no stale state.
        let good = data.clone();
        let (server, addr) = stub_server();
        let server_thread = thread::spawn(move || {
            if let Ok(request) = server.recv() {
                respond(request, 200, good, &[]);
            }
        });
        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);
        let (result, sink) =
            run_controlled(&params, &DownloadControl::new(), &runtime, &mut |_| {});
        server_thread.join().expect("server thread");

        let report = result.expect("retry succeeds");
        assert_eq!(report.state, DownloadState::Done);
        assert_eq!(report.sha256.as_deref(), Some(sha256_hex(&data).as_str()));
        assert_eq!(fs::read(&dest).expect("final file"), data);
        assert_eq!(sink.flushes, 1);
    }

    #[test]
    fn stale_installers_next_to_the_destination_are_cleaned_up() {
        let data = sample_bytes(64 * 1024);
        let body = data.clone();
        let (server, addr) = stub_server();
        let server_thread = thread::spawn(move || {
            if let Ok(request) = server.recv() {
                respond(request, 200, body, &[]);
            }
        });

        let dir = tempdir().expect("tempdir");
        let dest = seeded_dest(&dir);
        let old = dir.path().join("FreeAssetFilter_Setup_1.2.3.exe");
        let portable = dir.path().join("freeassetfilter_portable.EXE");
        let unrelated = dir.path().join("other.exe");
        let folder = dir.path().join("freeassetfilter_folder.exe");
        fs::write(&old, b"old").expect("old installer");
        fs::write(&portable, b"old").expect("portable installer");
        fs::write(&unrelated, b"keep").expect("unrelated");
        fs::create_dir(&folder).expect("folder");

        let params = params_for(format!("http://{addr}/asset.exe"), &dest, &data, true);
        let runtime = DownloadRuntime::isolated(default_config(), RecordingAction::new());
        let (result, _sink) =
            run_controlled(&params, &DownloadControl::new(), &runtime, &mut |_| {});
        server_thread.join().expect("server thread");

        assert_eq!(
            result.expect("download succeeds").state,
            DownloadState::Done
        );
        assert!(!old.exists(), "previous installer removed");
        assert!(!portable.exists(), "previous portable installer removed");
        assert!(unrelated.exists(), "unrelated executables untouched");
        assert!(folder.exists(), "directories untouched");
        assert!(dest.exists(), "the new installer is kept");
    }

    #[test]
    fn verify_file_matches_hashes_and_reports_file_identity() {
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("FreeAssetFilter_Setup.exe");
        let data = sample_bytes(3 * MIB + 17);
        fs::write(&path, &data).expect("write asset");
        let expected = sha256_hex(&data);

        let report = verify_file(&path, &expected.to_uppercase()).expect("verify");
        assert!(report.match_, "uppercase hex must still match");
        assert_eq!(report.actual, expected);
        assert!(report.file_index > 0, "NTFS file index is reported");
        let json = serde_json::to_value(&report).expect("serialize");
        assert_eq!(
            json.get("match").and_then(|value| value.as_bool()),
            Some(true)
        );
        assert!(json.get("sha256").is_none());
    }

    #[test]
    fn verify_file_rejects_bad_hashes_and_missing_paths() {
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("setup.exe");
        fs::write(&path, b"payload").expect("write");

        let error = verify_file(&path, "not-a-sha").expect_err("bad hash rejected");
        assert_eq!(error.code, ErrorCode::BadParams);

        let error = verify_file(&dir.path().join("missing.exe"), &sha256_hex(b"payload"))
            .expect_err("missing file rejected");
        assert_eq!(error.code, ErrorCode::Io);
    }

    #[test]
    fn verify_file_rejects_reparse_points_when_symlinks_are_available() {
        let dir = tempdir().expect("tempdir");
        let target = dir.path().join("real.exe");
        let data = sample_bytes(4096);
        fs::write(&target, &data).expect("write target");
        let link = dir.path().join("link.exe");
        match std::os::windows::fs::symlink_file(&target, &link) {
            Ok(()) => {
                let error = verify_file(&link, &sha256_hex(&data))
                    .expect_err("a symlink must never verify");
                assert_eq!(error.code, ErrorCode::Io);
            }
            Err(error) => {
                eprintln!("skipping reparse test: symlink creation unavailable ({error})");
            }
        }
    }

    #[test]
    fn retry_policy_is_bounded_and_matches_the_plan_budget() {
        let policy = RetryPolicy::standard();
        assert_eq!(policy.max_attempts, 3);
        assert_eq!(policy.delay_before(1), Duration::from_secs(1));
        assert_eq!(policy.delay_before(2), Duration::from_secs(2));
        assert_eq!(policy.delay_before(3), Duration::from_secs(4));
        assert!(RetryPolicy::immediate().delay_before(9).is_zero());
    }
}
