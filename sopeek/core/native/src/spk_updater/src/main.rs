//! `spk_updater.exe` - standalone updater sidecar.
//!
//! Reads one NDJSON command per stdin line and writes one NDJSON reply/event
//! per stdout line. `check` and `verify` run on worker threads, `download` owns
//! a long-lived worker with pause/cancel control, and `shutdown`/EOF flush
//! part+meta before exiting. Every reply/event is serialized by [`LineWriter`],
//! which can be closed to guarantee no protocol output after stdin EOF.

mod check;
mod download;
mod error;
mod http;
mod protocol;
mod release;
mod state;
mod version;
mod watchdog;

#[cfg(test)]
mod tests;

use std::fs;
use std::io::{self, BufRead, Write};
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::{json, Value};

use crate::download::{
    execute_download_with_control, verify_file, DownloadControl, DownloadParams, DownloadRuntime,
    DownloadSink,
};
use crate::error::{AppError, ErrorCode};
use crate::protocol::{DownloadState, Event, Request, Response};
use crate::watchdog::{WatchdogAction, WatchdogConfig};

/// Serializes stdout access and flushes after every line.
///
/// `check` and `verify` run on their own threads, so writes must be serialized
/// by exactly one lock and each line must be flushed immediately: the Python
/// bridge reads line-by-line and applies per-command timeouts. After
/// [`LineWriter::close`], writes are silent no-ops that still report success;
/// this is what makes the stdin-EOF path (shutdown without an ack) incapable of
/// emitting a terminal state line, even if a worker races the pause request.
pub struct LineWriter<W: Write> {
    inner: Mutex<WriterSink<W>>,
}

struct WriterSink<W: Write> {
    sink: W,
    closed: bool,
}

impl<W: Write> LineWriter<W> {
    /// Wraps a sink (stdout in production, an in-memory recorder in tests).
    pub fn new(inner: W) -> Self {
        Self {
            inner: Mutex::new(WriterSink {
                sink: inner,
                closed: false,
            }),
        }
    }

    /// Writes one line, adding a trailing newline when absent, then flushes.
    pub fn write_line(&self, line: &str) -> io::Result<()> {
        let line = line.strip_suffix('\n').unwrap_or(line);
        let mut out = self
            .inner
            .lock()
            .map_err(|_| io::Error::other("stdout lock poisoned"))?;
        if out.closed {
            // Success (rather than an error) keeps the download worker on its
            // normal flush-and-exit path after EOF; it just emits nothing.
            return Ok(());
        }
        out.sink.write_all(line.as_bytes())?;
        out.sink.write_all(b"\n")?;
        out.sink.flush()
    }

    /// Permanently closes protocol output after flushing in-flight bytes.
    ///
    /// Used only by the stdin-EOF path, where the contract is "shutdown without
    /// an ack": no further line may reach stdout, including a `paused` state or
    /// terminal response produced by the pause requested during shutdown.
    pub fn close(&self) -> io::Result<()> {
        let mut out = self
            .inner
            .lock()
            .map_err(|_| io::Error::other("stdout lock poisoned"))?;
        out.closed = true;
        out.sink.flush()
    }

    /// Serializes a protocol value as one NDJSON line.
    pub fn write_value<T: Serialize>(&self, value: &T) -> io::Result<()> {
        let encoded = serde_json::to_string(value)
            .map_err(|error| io::Error::other(format!("serialize protocol value: {error}")))?;
        self.write_line(&encoded)
    }
}

#[derive(Default)]
struct Registry {
    active: Option<ActiveDownload>,
    paused: Option<PausedDownload>,
    download_handle: Option<JoinHandle<()>>,
}

struct ActiveDownload {
    id: String,
    control: Arc<DownloadControl>,
}

struct PausedDownload {
    id: String,
    dest: PathBuf,
}

impl Registry {
    fn publish_terminal(&mut self, id: &str, dest: &Path, state: Option<DownloadState>) {
        if self.active.as_ref().is_some_and(|active| active.id == id) {
            self.active = None;
        }
        match state {
            Some(DownloadState::Paused) => {
                self.paused = Some(PausedDownload {
                    id: id.to_owned(),
                    dest: dest.to_path_buf(),
                });
            }
            Some(DownloadState::Done) | Some(DownloadState::Cancelled) => {
                if self.paused.as_ref().is_some_and(|paused| paused.id == id) {
                    self.paused = None;
                }
            }
            _ => {
                if self.paused.as_ref().is_some_and(|paused| paused.id == id) {
                    self.paused = None;
                }
            }
        }
    }
}

struct Sidecar<W: Write + Send + 'static> {
    writer: Arc<LineWriter<W>>,
    registry: Arc<Mutex<Registry>>,
}

impl<W: Write + Send + 'static> Sidecar<W> {
    fn start_check(&self, request: Request) -> io::Result<()> {
        let Request { id, params, .. } = request;
        let writer = Arc::clone(&self.writer);
        thread::spawn(move || {
            let response = match check::CheckParams::from_value(&params) {
                Ok(params) => match check::execute_check(&params) {
                    Ok(result) => Response::success(id, result),
                    Err(error) => Response::failure(id, &error),
                },
                Err(error) => Response::failure(id, &error),
            };
            let _ = writer.write_value(&response);
        });
        Ok(())
    }

    fn start_verify(&self, request: Request) -> io::Result<()> {
        let Request { id, params, .. } = request;
        let writer = Arc::clone(&self.writer);
        thread::spawn(move || {
            let response = match parse_verify_params(&params) {
                Ok((path, sha256)) => match verify_file(&path, &sha256) {
                    Ok(report) => match serde_json::to_value(&report) {
                        Ok(result) => Response::success(id, result),
                        Err(error) => Response::failure(
                            id,
                            &AppError::new(
                                ErrorCode::Internal,
                                format!("序列化验签结果失败：{error}"),
                            ),
                        ),
                    },
                    Err(error) => Response::failure(id, &error),
                },
                Err(error) => Response::failure(id, &error),
            };
            let _ = writer.write_value(&response);
        });
        Ok(())
    }

    fn start_download(&self, request: Request) -> io::Result<()> {
        let Request { id, params, .. } = request;
        let params = match DownloadParams::from_value(&params) {
            Ok(params) => params,
            Err(error) => return self.writer.write_value(&Response::failure(id, &error)),
        };

        let mut registry = self
            .registry
            .lock()
            .map_err(|_| io::Error::other("registry lock poisoned"))?;

        if let Some(active) = registry.active.as_ref() {
            let error = AppError::new(
                ErrorCode::Busy,
                format!("已有下载任务正在进行（{}），请稍后再试", active.id),
            );
            drop(registry);
            return self.writer.write_value(&Response::failure(id, &error));
        }

        let previous_handle = registry.download_handle.take();
        if let Some(previous) = previous_handle {
            // The worker's final act is writing its terminal line under the
            // registry lock, so joining while holding that lock would deadlock.
            // `download` reaches this method only from the single stdin reader,
            // so no other worker can register while the lock is released here.
            drop(registry);
            let _ = previous.join();
            registry = self
                .registry
                .lock()
                .map_err(|_| io::Error::other("registry lock poisoned"))?;
        }

        if let Some(paused) = registry.paused.take() {
            if paused.id != id || paused.dest != params.dest_path {
                cleanup_artifacts(&paused.dest);
            }
        }

        let control = Arc::new(DownloadControl::new());
        control.reset_for_request();

        let terminal_written = Arc::new(AtomicBool::new(false));
        let dest = params.dest_path.clone();
        let config = WatchdogConfig::from_env();
        let watchdog_action = Arc::new(SidecarWatchdogAction {
            writer: Arc::clone(&self.writer),
            registry: Arc::clone(&self.registry),
            id: id.clone(),
            dest: dest.clone(),
            control: Arc::clone(&control),
            idle_timeout_ms: config.idle_timeout_ms,
            terminal_written: Arc::clone(&terminal_written),
        });
        let runtime = DownloadRuntime::production(config, watchdog_action);
        let mut sink = SidecarSink {
            writer: Arc::clone(&self.writer),
            registry: Arc::clone(&self.registry),
            id: id.clone(),
            dest,
            terminal_written,
        };

        registry.active = Some(ActiveDownload {
            id: id.clone(),
            control: Arc::clone(&control),
        });
        let handle = thread::spawn(move || {
            let _ = execute_download_with_control(&id, &params, &mut sink, &control, &runtime);
        });
        registry.download_handle = Some(handle);
        drop(registry);
        Ok(())
    }

    fn control(&self, request: Request) -> io::Result<()> {
        let Request { id, cmd, params } = request;
        let target = match params
            .get("target")
            .and_then(Value::as_str)
            .filter(|target| !target.is_empty())
        {
            Some(target) => target.to_owned(),
            None => {
                return self.writer.write_value(&Response::failure(
                    id,
                    &AppError::new(
                        ErrorCode::BadParams,
                        format!("{cmd}.params.target 缺失或不是非空字符串"),
                    ),
                ));
            }
        };

        let (accepted, active_control, paused_cleanup) = {
            let mut registry = self
                .registry
                .lock()
                .map_err(|_| io::Error::other("registry lock poisoned"))?;
            if let Some(active) = registry.active.as_ref() {
                if active.id == target {
                    if cmd == "pause" {
                        let accepted = active.control.request_pause();
                        (
                            accepted,
                            accepted.then(|| Arc::clone(&active.control)),
                            None,
                        )
                    } else {
                        active.control.request_cancel();
                        (true, Some(Arc::clone(&active.control)), None)
                    }
                } else {
                    (false, None, None)
                }
            } else if let Some(paused) = registry.paused.as_ref() {
                if paused.id != target {
                    (false, None, None)
                } else if cmd == "pause" {
                    (true, None, None)
                } else {
                    let dest = paused.dest.clone();
                    registry.paused = None;
                    (true, None, Some(dest))
                }
            } else {
                (false, None, None)
            }
        };

        if let Some(dest) = paused_cleanup {
            cleanup_artifacts(&dest);
        }
        if accepted {
            if let Some(control) = active_control.as_ref() {
                control.request_watchdog_abort();
            }
        }

        self.writer
            .write_value(&Response::success(id, json!({"accepted": accepted})))?;

        if accepted {
            if let Some(control) = active_control {
                control.acknowledge_control();
            }
        }
        Ok(())
    }

    fn shutdown(&self, ack: Option<&str>) -> io::Result<()> {
        if ack.is_none() {
            // stdin EOF is "shutdown without an ack": close protocol output
            // BEFORE requesting the pause, so a worker that observes the pause
            // race can never emit `state:paused` or a terminal `paused` line.
            self.writer.close()?;
        }
        let handle = {
            let mut registry = self
                .registry
                .lock()
                .map_err(|_| io::Error::other("registry lock poisoned"))?;
            if let Some(active) = registry.active.as_ref() {
                let _ = active.control.request_pause();
            }
            registry.download_handle.take()
        };

        if let Some(handle) = handle {
            let deadline = Instant::now() + Duration::from_millis(1500);
            while !handle.is_finished() && Instant::now() < deadline {
                thread::sleep(Duration::from_millis(10));
            }
            if handle.is_finished() {
                let _ = handle.join();
            }
        }

        if let Some(id) = ack {
            self.writer.write_value(&Response::success(id, json!({})))?;
        }
        Ok(())
    }
}

struct SidecarSink<W: Write + Send + 'static> {
    writer: Arc<LineWriter<W>>,
    registry: Arc<Mutex<Registry>>,
    id: String,
    dest: PathBuf,
    terminal_written: Arc<AtomicBool>,
}

impl<W: Write + Send + 'static> DownloadSink for SidecarSink<W> {
    fn event(&mut self, event: &Event) -> io::Result<()> {
        if let Event::State {
            state: DownloadState::Paused,
            ..
        } = event
        {
            if let Ok(mut registry) = self.registry.lock() {
                registry.paused = Some(PausedDownload {
                    id: self.id.clone(),
                    dest: self.dest.clone(),
                });
            }
        }
        self.writer.write_value(event)
    }

    fn response(&mut self, response: &Response) -> io::Result<()> {
        if self.terminal_written.swap(true, Ordering::AcqRel) {
            return Ok(());
        }
        let state = response
            .result
            .as_ref()
            .and_then(|result| result.get("state"))
            .and_then(Value::as_str)
            .and_then(parse_state_name);
        // Write the terminal line while still holding the registry lock: the
        // next download registers (and its worker emits `resolving`) only after
        // acquiring the same lock, so a stale terminal line can never appear
        // after a newer request's first event on stdout.
        let mut registry = self
            .registry
            .lock()
            .map_err(|_| io::Error::other("registry lock poisoned"))?;
        registry.publish_terminal(&self.id, &self.dest, state);
        self.writer.write_value(response)
    }
}

struct SidecarWatchdogAction<W: Write + Send + 'static> {
    writer: Arc<LineWriter<W>>,
    registry: Arc<Mutex<Registry>>,
    id: String,
    dest: PathBuf,
    control: Arc<DownloadControl>,
    idle_timeout_ms: u64,
    terminal_written: Arc<AtomicBool>,
}

impl<W: Write + Send + 'static> WatchdogAction for SidecarWatchdogAction<W> {
    fn on_idle_timeout(&self) {
        if self.terminal_written.swap(true, Ordering::AcqRel) {
            return;
        }
        let error = AppError::new(
            ErrorCode::Timeout,
            format!("下载超时：{} 毫秒内没有收到新数据", self.idle_timeout_ms),
        );
        let response = Response::failure(self.id.as_str(), &error);
        if let Ok(mut registry) = self.registry.lock() {
            registry.publish_terminal(&self.id, &self.dest, None);
            let _ = self.writer.write_value(&response);
        } else {
            let _ = self.writer.write_value(&response);
        }
        std::process::exit(0);
    }

    fn on_control_abort(&self) {
        if self.terminal_written.swap(true, Ordering::AcqRel) {
            return;
        }
        let cancelled = self.control.cancel_requested();
        let part = state::part_path(&self.dest);
        let downloaded = fs::metadata(&part)
            .map(|metadata| metadata.len())
            .unwrap_or(0);
        // Plan acceptance contract: the forced pause/cancel path must NOT delete
        // artifacts that a live download handle may still hold; cleanup of a
        // cancelled part/meta belongs to the service layer, not the sidecar.
        let terminal_state = if cancelled {
            DownloadState::Cancelled
        } else {
            DownloadState::Paused
        };
        let response = Response::success(
            self.id.as_str(),
            json!({
                "state": if cancelled { "cancelled" } else { "paused" },
                "path": self.dest.to_string_lossy(),
                "downloaded": downloaded,
                "sha256": null,
            }),
        );
        if let Ok(mut registry) = self.registry.lock() {
            registry.publish_terminal(&self.id, &self.dest, Some(terminal_state));
            let _ = self.writer.write_value(&response);
        } else {
            let _ = self.writer.write_value(&response);
        }
        std::process::exit(0);
    }
}

fn cleanup_artifacts(dest: &Path) {
    let _ = state::remove_file_if_exists(&state::part_path(dest));
    let _ = state::remove_file_if_exists(&state::meta_path(dest));
}

fn parse_state_name(name: &str) -> Option<DownloadState> {
    match name {
        "resolving" => Some(DownloadState::Resolving),
        "downloading" => Some(DownloadState::Downloading),
        "paused" => Some(DownloadState::Paused),
        "verifying" => Some(DownloadState::Verifying),
        "done" => Some(DownloadState::Done),
        "cancelled" => Some(DownloadState::Cancelled),
        _ => None,
    }
}

fn parse_verify_params(value: &Value) -> Result<(PathBuf, String), AppError> {
    let object = value
        .as_object()
        .ok_or_else(|| AppError::new(ErrorCode::BadParams, "verify 参数必须是 JSON 对象"))?;
    let raw_path = object
        .get("path")
        .and_then(Value::as_str)
        .filter(|path| !path.is_empty())
        .ok_or_else(|| AppError::new(ErrorCode::BadParams, "verify.path 缺失或不是字符串"))?;
    let path = PathBuf::from(raw_path);
    if !path.is_absolute() {
        return Err(AppError::new(
            ErrorCode::BadParams,
            "verify.path 必须是绝对路径",
        ));
    }
    if path
        .components()
        .any(|component| matches!(component, Component::ParentDir))
    {
        return Err(AppError::new(
            ErrorCode::BadParams,
            "verify.path 不能包含 ..",
        ));
    }
    let sha256 = object
        .get("sha256")
        .and_then(Value::as_str)
        .filter(|hash| is_sha256_hex(hash))
        .ok_or_else(|| {
            AppError::new(
                ErrorCode::BadParams,
                "verify.sha256 必须是 64 位十六进制字符串",
            )
        })?;
    Ok((path, sha256.to_ascii_lowercase()))
}

fn is_sha256_hex(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

/// Serves commands until stdin reaches EOF, using the threaded runtime.
pub fn serve_sidecar<R: BufRead, W: Write + Send + 'static>(
    input: R,
    writer: LineWriter<W>,
) -> io::Result<()> {
    let writer = Arc::new(writer);
    let sidecar = Sidecar {
        writer: Arc::clone(&writer),
        registry: Arc::new(Mutex::new(Registry::default())),
    };

    for line in input.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let request = match protocol::parse_request(&line) {
            Ok(request) => request,
            Err(error) => {
                writer.write_value(&Response::failure(String::new(), &error))?;
                continue;
            }
        };
        let cmd = request.cmd.clone();
        match cmd.as_str() {
            "hello" => {
                let id = request.id;
                writer.write_value(&Response::success(
                    id,
                    json!({
                        "protocol": protocol::PROTOCOL_VERSION,
                        "version": env!("CARGO_PKG_VERSION"),
                    }),
                ))?;
            }
            "check" => sidecar.start_check(request)?,
            "download" => sidecar.start_download(request)?,
            "pause" | "cancel" => sidecar.control(request)?,
            "verify" => sidecar.start_verify(request)?,
            "shutdown" => {
                let id = request.id;
                sidecar.shutdown(Some(&id))?;
                return Ok(());
            }
            other => {
                let id = request.id;
                writer.write_value(&Response::failure(
                    id,
                    &AppError::new(ErrorCode::BadCommand, format!("未知命令：{other}")),
                ))?;
            }
        }
    }

    sidecar.shutdown(None)
}

/// Serves commands synchronously until stdin reaches EOF.
///
/// Retained as the unit-test seam used by the protocol tests; the real binary
/// uses [`serve_sidecar`] so `check`/`verify` cannot block stdin.
#[allow(dead_code)]
pub fn serve<R: BufRead, W: Write>(input: R, writer: &LineWriter<W>) -> io::Result<()> {
    for line in input.lines() {
        let line = line?;
        if let Some(response) = protocol::handle_line(&line) {
            writer.write_value(&response)?;
        }
    }
    Ok(())
}

fn main() {
    let writer = LineWriter::new(io::stdout());
    let stdin = io::stdin();
    if let Err(error) = serve_sidecar(stdin.lock(), writer) {
        let _ = writeln!(io::stderr(), "spk_updater stdin/stdout error: {error}");
    }
}

#[cfg(test)]
mod line_writer_tests {
    use super::*;
    use std::io::Cursor;
    use std::sync::Arc;

    #[derive(Clone, Default)]
    struct RecordingSink(Arc<Mutex<SinkState>>);

    #[derive(Default)]
    struct SinkState {
        bytes: Vec<u8>,
        flushes: usize,
    }

    impl RecordingSink {
        fn snapshot(&self) -> (String, usize) {
            let state = self.0.lock().expect("sink lock");
            (
                String::from_utf8(state.bytes.clone()).expect("utf8"),
                state.flushes,
            )
        }
    }

    impl Write for RecordingSink {
        fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
            self.0
                .lock()
                .expect("sink lock")
                .bytes
                .extend_from_slice(buffer);
            Ok(buffer.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            self.0.lock().expect("sink lock").flushes += 1;
            Ok(())
        }
    }

    #[test]
    fn each_line_is_flushed_exactly_once() {
        let sink = RecordingSink::default();
        let writer = LineWriter::new(sink.clone());
        writer.write_line("first").expect("write");
        writer.write_line("second\n").expect("write");

        let (text, flushes) = sink.snapshot();
        assert_eq!(text, "first\nsecond\n");
        assert_eq!(flushes, 2, "every line must be flushed");
    }

    #[test]
    fn json_values_are_written_as_single_lines() {
        let sink = RecordingSink::default();
        let writer = LineWriter::new(sink.clone());
        writer
            .write_value(&serde_json::json!({"id": "c1", "ok": true}))
            .expect("write");

        let (text, flushes) = sink.snapshot();
        assert_eq!(text, "{\"id\":\"c1\",\"ok\":true}\n");
        assert_eq!(flushes, 1);
    }

    #[test]
    fn close_flushes_and_silently_drops_later_lines() {
        let sink = RecordingSink::default();
        let writer = LineWriter::new(sink.clone());
        writer.write_line("before").expect("write");
        writer.close().expect("close");

        // Post-close writes must report success so the download worker still
        // reaches its flush-and-exit path, but they must emit nothing.
        writer
            .write_line("after")
            .expect("post-close write is a no-op");
        writer
            .write_value(&serde_json::json!({"state": "paused"}))
            .expect("post-close value write is a no-op");
        assert!(writer.close().is_ok(), "close must be idempotent");

        let (text, _) = sink.snapshot();
        assert_eq!(text, "before\n", "no bytes may follow close()");
    }

    #[test]
    fn serve_keeps_going_after_invalid_json() {
        let input = concat!(
            "{\"id\":\"bad\"",
            "\n",
            "{\"id\":\"c2\",\"cmd\":\"hello\",\"params\":{}}",
            "\n",
        );
        let sink = RecordingSink::default();
        let writer = LineWriter::new(sink.clone());
        serve(Cursor::new(input), &writer).expect("serve");

        let (text, flushes) = sink.snapshot();
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 2, "both commands must be answered");
        assert_eq!(flushes, 2);

        let invalid: serde_json::Value = serde_json::from_str(lines[0]).expect("json");
        assert_eq!(invalid["ok"], serde_json::json!(false));
        assert_eq!(invalid["error"]["code"], serde_json::json!("invalid_json"));

        let hello: serde_json::Value = serde_json::from_str(lines[1]).expect("json");
        assert_eq!(hello["id"], serde_json::json!("c2"));
        assert_eq!(hello["ok"], serde_json::json!(true));
        assert_eq!(hello["result"]["protocol"], serde_json::json!(1));
    }

    #[test]
    fn blank_lines_are_silently_skipped() {
        let input = "\n   \n{\"id\":\"c1\",\"cmd\":\"hello\"}\n";
        let sink = RecordingSink::default();
        let writer = LineWriter::new(sink.clone());
        serve(Cursor::new(input), &writer).expect("serve");

        let (text, _) = sink.snapshot();
        assert_eq!(text.lines().count(), 1);
    }
}
