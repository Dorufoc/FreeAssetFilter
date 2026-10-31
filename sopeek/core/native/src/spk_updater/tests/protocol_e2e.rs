//! End-to-end protocol tests against the real `spk_updater` binary.
//!
//! Every test drives the compiled sidecar over stdin/stdout NDJSON and uses
//! loopback TCP stubs only. No real GitHub request is ever made.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::{Shutdown, SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

const MIB: usize = 1024 * 1024;

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_spk_updater")
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn sample_body_sized(len: usize) -> Vec<u8> {
    (0..len).map(|index| (index % 251) as u8).collect()
}

fn sample_body() -> Vec<u8> {
    sample_body_sized(MIB)
}

fn release_fixture() -> Vec<u8> {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../../../../tests/fixtures/releases.json");
    std::fs::read(&path).unwrap_or_else(|error| {
        panic!("failed to read release fixture {}: {error}", path.display())
    })
}

/// NDJSON session around one real sidecar process.
struct Session {
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    lines: Receiver<String>,
    captured: Arc<Mutex<Vec<String>>>,
    stdout_reader: Option<JoinHandle<()>>,
    stderr_reader: Option<JoinHandle<()>>,
    stderr: Arc<Mutex<String>>,
}

impl Session {
    fn spawn(env: &[(&str, &str)]) -> Self {
        let mut command = Command::new(binary());
        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        for (key, value) in env {
            command.env(key, value);
        }
        let mut child = command.spawn().expect("spawn spk_updater");
        let stdin = child.stdin.take().expect("stdin");
        let stdout = child.stdout.take().expect("stdout");
        let stderr = child.stderr.take().expect("stderr");

        let (sender, receiver) = mpsc::channel();
        let captured = Arc::new(Mutex::new(Vec::new()));
        let captured_reader = Arc::clone(&captured);
        let stdout_reader = thread::spawn(move || {
            let reader = BufReader::new(stdout);
            for line in reader.lines() {
                let line = match line {
                    Ok(line) => line,
                    Err(_) => break,
                };
                let parsed: Value = serde_json::from_str(&line)
                    .unwrap_or_else(|error| panic!("non-JSON stdout line {line:?}: {error}"));
                assert!(
                    parsed.is_object(),
                    "stdout line must be a JSON object: {line}"
                );
                captured_reader.lock().expect("captured").push(line.clone());
                if sender.send(line).is_err() {
                    break;
                }
            }
        });

        let stderr_buffer = Arc::new(Mutex::new(String::new()));
        let stderr_sink = Arc::clone(&stderr_buffer);
        let stderr_reader = thread::spawn(move || {
            let mut reader = BufReader::new(stderr);
            let mut text = String::new();
            let _ = reader.read_to_string(&mut text);
            stderr_sink.lock().expect("stderr").push_str(&text);
        });

        Self {
            child: Some(child),
            stdin: Some(stdin),
            lines: receiver,
            captured,
            stdout_reader: Some(stdout_reader),
            stderr_reader: Some(stderr_reader),
            stderr: stderr_buffer,
        }
    }

    fn send(&mut self, value: Value) {
        let encoded = serde_json::to_string(&value).expect("encode request");
        let stdin = self.stdin.as_mut().expect("stdin still open");
        writeln!(stdin, "{encoded}").expect("write request");
        stdin.flush().expect("flush request");
    }

    fn request(&mut self, id: &str, cmd: &str, params: Value) {
        self.send(json!({"id": id, "cmd": cmd, "params": params}));
    }

    fn close_stdin(&mut self) {
        self.stdin.take();
    }

    fn stderr_text(&self) -> String {
        self.stderr.lock().expect("stderr").clone()
    }

    fn captured_lines(&self) -> Vec<String> {
        self.captured.lock().expect("captured").clone()
    }

    fn recv_matching(
        &mut self,
        timeout: Duration,
        mut predicate: impl FnMut(&Value) -> bool,
    ) -> Value {
        let deadline = Instant::now() + timeout;
        loop {
            let now = Instant::now();
            if now >= deadline {
                panic!(
                    "timed out after {timeout:?} waiting for matching line; captured={:?}; stderr={}",
                    self.captured_lines(),
                    self.stderr_text()
                );
            }
            match self
                .lines
                .recv_timeout(deadline.saturating_duration_since(now))
            {
                Ok(line) => {
                    let value: Value = serde_json::from_str(&line).expect("stdout JSON");
                    if predicate(&value) {
                        return value;
                    }
                }
                Err(RecvTimeoutError::Timeout) => {
                    panic!(
                        "timed out after {timeout:?}; captured={:?}; stderr={}",
                        self.captured_lines(),
                        self.stderr_text()
                    );
                }
                Err(RecvTimeoutError::Disconnected) => {
                    panic!(
                        "stdout closed before match; captured={:?}; stderr={}",
                        self.captured_lines(),
                        self.stderr_text()
                    );
                }
            }
        }
    }

    fn wait_response(&mut self, id: &str, timeout: Duration) -> Value {
        self.recv_matching(timeout, |value| {
            value.get("event").is_none() && value["id"] == json!(id)
        })
    }

    fn wait_state_event(&mut self, id: &str, state: &str, timeout: Duration) -> Value {
        self.recv_matching(timeout, |value| {
            value["event"] == json!("state")
                && value["id"] == json!(id)
                && value["state"] == json!(state)
        })
    }

    fn response_index(&self, id: &str) -> Option<usize> {
        for (index, line) in self.captured_lines().iter().enumerate() {
            let value: Value = serde_json::from_str(line).expect("stdout JSON");
            if value.get("event").is_none() && value["id"] == json!(id) {
                return Some(index);
            }
        }
        None
    }

    fn response_count(&self, id: &str) -> usize {
        self.captured_lines()
            .iter()
            .filter_map(|line| serde_json::from_str::<Value>(line).ok())
            .filter(|value| value.get("event").is_none() && value["id"] == json!(id))
            .count()
    }

    /// Asserts the number of terminal lines for `id`, dumping every captured
    /// line and stderr on mismatch so a race is diagnosable from CI output.
    fn assert_response_count(&self, id: &str, expected: usize, context: &str) {
        let count = self.response_count(id);
        if count != expected {
            panic!(
                "{context}: expected {expected} terminal line(s) for {id}, got {count}; \
                 captured={:?}; stderr={}",
                self.captured_lines(),
                self.stderr_text()
            );
        }
    }

    /// Joins both output readers so every byte the child wrote before exiting
    /// has reached `captured` before an assertion inspects it.
    fn drain_output(&mut self) {
        if let Some(handle) = self.stdout_reader.take() {
            let _ = handle.join();
        }
        if let Some(handle) = self.stderr_reader.take() {
            let _ = handle.join();
        }
    }

    fn wait_exit(&mut self, timeout: Duration) -> ExitStatus {
        let deadline = Instant::now() + timeout;
        loop {
            let status = self
                .child
                .as_mut()
                .and_then(|child| child.try_wait().expect("try_wait"));
            if let Some(status) = status {
                self.drain_output();
                return status;
            }
            if Instant::now() >= deadline {
                panic!(
                    "child did not exit within {timeout:?}; captured={:?}; stderr={}",
                    self.captured_lines(),
                    self.stderr_text()
                );
            }
            thread::sleep(Duration::from_millis(10));
        }
    }
}

impl Drop for Session {
    fn drop(&mut self) {
        self.stdin.take();
        if let Some(mut child) = self.child.take() {
            if child.try_wait().ok().flatten().is_none() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
        if let Some(handle) = self.stdout_reader.take() {
            let _ = handle.join();
        }
        if let Some(handle) = self.stderr_reader.take() {
            let _ = handle.join();
        }
    }
}

#[derive(Clone, Copy, Debug)]
enum StubMode {
    Full,
    Paced,
    Stall,
    PacedThenStall {
        paced_connections: usize,
    },
    /// Sends headers plus `prefix` body bytes, then stalls until `stop`.
    PartialStall {
        prefix: usize,
    },
}

struct StubServer {
    addr: SocketAddr,
    stop: Arc<AtomicBool>,
    accept: Option<JoinHandle<()>>,
}

impl StubServer {
    fn start(
        body: Vec<u8>,
        mode: StubMode,
        chunk: usize,
        chunk_delay: Duration,
        response_delay: Duration,
    ) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind stub");
        listener.set_nonblocking(true).expect("nonblocking");
        let addr = listener.local_addr().expect("local addr");
        let stop = Arc::new(AtomicBool::new(false));
        let accept_stop = Arc::clone(&stop);
        let body = Arc::new(body);
        let connections = Arc::new(AtomicUsize::new(0));
        let accept = thread::spawn(move || {
            while !accept_stop.load(Ordering::Acquire) {
                match listener.accept() {
                    Ok((stream, _)) => {
                        // Windows inherits the listener's non-blocking mode on
                        // accepted sockets; force blocking so partial writes
                        // and header reads never fail with WouldBlock (which
                        // would drop the connection and surface as 10053/10054).
                        if stream.set_nonblocking(false).is_err() {
                            continue;
                        }
                        let body = Arc::clone(&body);
                        let stop = Arc::clone(&accept_stop);
                        let connections = Arc::clone(&connections);
                        thread::spawn(move || {
                            serve_connection(
                                stream,
                                body,
                                mode,
                                chunk,
                                chunk_delay,
                                response_delay,
                                stop,
                                connections,
                            );
                        });
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(5));
                    }
                    Err(_) => break,
                }
            }
        });
        Self {
            addr,
            stop,
            accept: Some(accept),
        }
    }

    fn base_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.addr.port())
    }
}

impl Drop for StubServer {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        let _ = TcpStream::connect(self.addr);
        if let Some(handle) = self.accept.take() {
            let _ = handle.join();
        }
    }
}

fn parse_range(headers: &[String]) -> u64 {
    for header in headers {
        let Some((name, value)) = header.split_once(':') else {
            continue;
        };
        if !name.eq_ignore_ascii_case("range") {
            continue;
        }
        let Some(spec) = value.trim().strip_prefix("bytes=") else {
            continue;
        };
        let start = spec.split('-').next().unwrap_or("0");
        if let Ok(offset) = start.parse::<u64>() {
            return offset;
        }
    }
    0
}

#[allow(clippy::too_many_arguments)]
fn serve_connection(
    mut stream: TcpStream,
    body: Arc<Vec<u8>>,
    mode: StubMode,
    chunk: usize,
    chunk_delay: Duration,
    response_delay: Duration,
    stop: Arc<AtomicBool>,
    connections: Arc<AtomicUsize>,
) {
    let mut reader = match stream.try_clone() {
        Ok(clone) => BufReader::new(clone),
        Err(_) => return,
    };
    let mut request_line = String::new();
    if reader.read_line(&mut request_line).is_err() {
        return;
    }
    let mut headers = Vec::new();
    loop {
        let mut line = String::new();
        match reader.read_line(&mut line) {
            Ok(0) => break,
            Ok(_) => {
                if line == "\r\n" || line == "\n" {
                    break;
                }
                headers.push(line);
            }
            Err(_) => return,
        }
    }

    if !response_delay.is_zero() {
        let deadline = Instant::now() + response_delay;
        while Instant::now() < deadline && !stop.load(Ordering::Acquire) {
            thread::sleep(Duration::from_millis(10));
        }
    }

    let total = body.len() as u64;
    let start = parse_range(&headers).min(total);
    let remaining = total - start;
    let status = if start > 0 { 206 } else { 200 };
    let mut head = format!(
        "HTTP/1.1 {status} {}\r\nContent-Length: {remaining}\r\nContent-Type: application/octet-stream\r\nConnection: close\r\n",
        if status == 206 { "Partial Content" } else { "OK" }
    );
    if status == 206 {
        head.push_str(&format!(
            "Content-Range: bytes {}-{}/{}\r\n",
            start,
            total - 1,
            total
        ));
    }
    head.push_str("\r\n");
    if stream.write_all(head.as_bytes()).is_err() {
        return;
    }
    let _ = stream.flush();

    let effective = match mode {
        StubMode::PacedThenStall { paced_connections } => {
            if connections.fetch_add(1, Ordering::SeqCst) < paced_connections {
                StubMode::Paced
            } else {
                StubMode::Stall
            }
        }
        other => other,
    };

    match effective {
        StubMode::Full => {
            let _ = stream.write_all(&body[start as usize..]);
            let _ = stream.flush();
        }
        StubMode::Paced => {
            for piece in body[start as usize..].chunks(chunk.max(1)) {
                if stop.load(Ordering::Acquire) {
                    break;
                }
                if stream.write_all(piece).is_err() {
                    break;
                }
                let _ = stream.flush();
                if !chunk_delay.is_zero() {
                    thread::sleep(chunk_delay);
                }
            }
        }
        StubMode::Stall => {
            while !stop.load(Ordering::Acquire) {
                thread::sleep(Duration::from_millis(10));
            }
        }
        StubMode::PartialStall { prefix } => {
            let from = start as usize;
            let end = from.saturating_add(prefix).min(body.len());
            for piece in body[from..end].chunks(chunk.max(1)) {
                if stop.load(Ordering::Acquire) {
                    break;
                }
                if stream.write_all(piece).is_err() {
                    break;
                }
                let _ = stream.flush();
                if !chunk_delay.is_zero() {
                    thread::sleep(chunk_delay);
                }
            }
            // Keep the connection open with no further bytes: the download is
            // now blocked inside a read, exactly like a stalled CDN.
            while !stop.load(Ordering::Acquire) {
                thread::sleep(Duration::from_millis(10));
            }
        }
        StubMode::PacedThenStall { .. } => unreachable!("resolved above"),
    }

    // Half-close and drain so the peer observes a clean FIN instead of a RST
    // that could mask a real protocol failure as `network`.
    let _ = stream.shutdown(Shutdown::Write);
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let mut drain = [0u8; 4096];
    loop {
        match reader.read(&mut drain) {
            Ok(0) | Err(_) => break,
            Ok(_) => {}
        }
    }
    let _ = stream.shutdown(Shutdown::Both);
}

fn check_params(stub: &StubServer) -> Value {
    json!({
        "repo": "Dorufoc/Sopeek",
        "current_version": "1.0.0-alpha.5",
        "current_date": null,
        "include_prerelease": true,
        "api_base": stub.base_url(),
    })
}

fn download_params(stub: &StubServer, dest: &Path, body: &[u8]) -> Value {
    json!({
        "source_url": format!("{}/asset.exe", stub.base_url()),
        "dest_path": dest.to_string_lossy().to_string(),
        "expected_sha256": sha256_hex(body),
        "expected_size": body.len() as u64,
        "allow_insecure_localhost": true,
    })
}

fn artifact_paths(dest: &Path) -> (PathBuf, PathBuf) {
    let part = PathBuf::from(format!("{}.part", dest.display()));
    let meta = PathBuf::from(format!("{}.part.json", dest.display()));
    (part, meta)
}

/// Waits until the `.part` file holds at least `min` bytes, proving the worker
/// consumed everything the stub sent before the stall.
fn wait_for_part_len(part: &Path, min: u64) {
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        let len = std::fs::metadata(part)
            .map(|metadata| metadata.len())
            .unwrap_or(0);
        if len >= min {
            return;
        }
        if Instant::now() >= deadline {
            panic!(
                "part file {} did not reach {min} bytes (observed {len})",
                part.display()
            );
        }
        thread::sleep(Duration::from_millis(10));
    }
}

fn assert_success(status: ExitStatus) {
    assert!(status.success(), "child exited with {status:?}");
}

#[test]
fn happy_path_hello_check_download_shutdown() {
    let check_stub = StubServer::start(
        release_fixture(),
        StubMode::Full,
        64 * 1024,
        Duration::ZERO,
        Duration::ZERO,
    );
    let body = sample_body();
    let download_stub = StubServer::start(
        body.clone(),
        StubMode::Full,
        64 * 1024,
        Duration::ZERO,
        Duration::ZERO,
    );
    let dir = tempfile::tempdir().expect("tempdir");
    let dest = dir.path().join("Sopeek_Setup.exe");

    let mut session = Session::spawn(&[]);
    session.request("c1", "hello", json!({}));
    let hello = session.wait_response("c1", Duration::from_secs(5));
    assert_eq!(hello["ok"], json!(true));
    assert_eq!(hello["result"]["protocol"], json!(1));
    assert_eq!(hello["result"]["version"], json!(env!("CARGO_PKG_VERSION")));

    session.request("c2", "check", check_params(&check_stub));
    let check = session.wait_response("c2", Duration::from_secs(15));
    assert_eq!(check["ok"], json!(true), "check failed: {check}");
    assert_eq!(check["result"]["update_available"], json!(true));
    assert!(check["result"]["asset"]["name"].is_string());

    session.request(
        "d1",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    let download = session.wait_response("d1", Duration::from_secs(20));
    assert_eq!(download["ok"], json!(true), "download failed: {download}");
    assert_eq!(download["result"]["state"], json!("done"));
    assert_eq!(download["result"]["sha256"], json!(sha256_hex(&body)));
    assert_eq!(
        std::fs::read(&dest).expect("final file"),
        body,
        "final installer bytes must match the stub"
    );

    session.request("s1", "shutdown", json!({}));
    let ack = session.wait_response("s1", Duration::from_secs(5));
    assert_eq!(ack["ok"], json!(true));
    assert_success(session.wait_exit(Duration::from_secs(5)));
}

#[test]
fn pause_is_acked_while_a_slow_check_is_still_running() {
    let check_stub = StubServer::start(
        release_fixture(),
        StubMode::Full,
        64 * 1024,
        Duration::ZERO,
        Duration::from_secs(3),
    );
    // 4 MiB at 8 KiB/25 ms (~12.8 s) keeps the download running long past the
    // 3 s check delay, so "pause while the check is in flight" is not a race.
    let body = sample_body_sized(4 * MIB);
    let download_stub = StubServer::start(
        body.clone(),
        StubMode::Paced,
        8 * 1024,
        Duration::from_millis(25),
        Duration::ZERO,
    );
    let dir = tempfile::tempdir().expect("tempdir");
    let dest = dir.path().join("Sopeek_Setup.exe");

    let mut session = Session::spawn(&[]);
    session.request(
        "d1",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    session.wait_state_event("d1", "downloading", Duration::from_secs(5));

    session.request("c2", "check", check_params(&check_stub));
    thread::sleep(Duration::from_millis(100));
    session.request("p1", "pause", json!({"target": "d1"}));

    let started = Instant::now();
    let ack = session.wait_response("p1", Duration::from_secs(5));
    let elapsed = started.elapsed();
    assert_eq!(ack["ok"], json!(true));
    assert_eq!(ack["result"]["accepted"], json!(true));
    assert_eq!(
        ack["id"],
        json!("p1"),
        "ack id must be the control request id"
    );
    assert!(
        elapsed < Duration::from_millis(1500),
        "pause ack took {elapsed:?}; a 3s check must not starve control commands"
    );
    assert!(
        session.response_index("c2").is_none(),
        "check should still be in flight when the pause ack lands"
    );

    let paused = session.wait_response("d1", Duration::from_secs(5));
    assert_eq!(paused["ok"], json!(true));
    assert_eq!(paused["result"]["state"], json!("paused"));

    session.request("s1", "shutdown", json!({}));
    let ack = session.wait_response("s1", Duration::from_secs(5));
    assert_eq!(ack["ok"], json!(true));
    assert_success(session.wait_exit(Duration::from_secs(5)));
}

#[test]
fn zero_byte_stall_pause_writes_paused_then_exits_zero() {
    let body = sample_body();
    let download_stub = StubServer::start(
        body.clone(),
        StubMode::Stall,
        8 * 1024,
        Duration::ZERO,
        Duration::ZERO,
    );
    let dir = tempfile::tempdir().expect("tempdir");
    let dest = dir.path().join("Sopeek_Setup.exe");

    let mut session = Session::spawn(&[("SPK_UPDATER_IDLE_TIMEOUT_MS", "400")]);
    session.request(
        "d1",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    session.wait_state_event("d1", "downloading", Duration::from_secs(5));

    session.request("p1", "pause", json!({"target": "d1"}));
    let ack = session.wait_response("p1", Duration::from_secs(5));
    assert_eq!(ack["ok"], json!(true));
    assert_eq!(ack["result"]["accepted"], json!(true));

    let paused = session.wait_response("d1", Duration::from_secs(3));
    assert_eq!(paused["ok"], json!(true), "pause must not become timeout");
    assert_eq!(paused["result"]["state"], json!("paused"));
    assert_success(session.wait_exit(Duration::from_secs(3)));
    assert_eq!(session.response_count("d1"), 1, "exactly one terminal line");

    let (part, meta) = artifact_paths(&dest);
    assert!(part.exists(), "stalled pause must keep the part file");
    assert!(meta.exists(), "stalled pause must keep the resume metadata");
}

#[test]
fn zero_byte_stall_cancel_writes_cancelled_then_exits_zero() {
    let body = sample_body();
    let download_stub = StubServer::start(
        body.clone(),
        StubMode::Stall,
        8 * 1024,
        Duration::ZERO,
        Duration::ZERO,
    );
    let dir = tempfile::tempdir().expect("tempdir");
    let dest = dir.path().join("Sopeek_Setup.exe");

    let mut session = Session::spawn(&[("SPK_UPDATER_IDLE_TIMEOUT_MS", "400")]);
    session.request(
        "d1",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    session.wait_state_event("d1", "downloading", Duration::from_secs(5));

    session.request("p1", "cancel", json!({"target": "d1"}));
    let ack = session.wait_response("p1", Duration::from_secs(5));
    assert_eq!(ack["ok"], json!(true));
    assert_eq!(ack["result"]["accepted"], json!(true));

    let cancelled = session.wait_response("d1", Duration::from_secs(3));
    assert_eq!(
        cancelled["ok"],
        json!(true),
        "cancel must not become timeout"
    );
    assert_eq!(cancelled["result"]["state"], json!("cancelled"));
    assert_success(session.wait_exit(Duration::from_secs(3)));
    assert_eq!(session.response_count("d1"), 1, "exactly one terminal line");
}

#[test]
fn partial_body_stall_pause_flushes_paused_and_keeps_artifacts() {
    let body = sample_body_sized(4 * MIB);
    let prefix = 512 * 1024;
    let download_stub = StubServer::start(
        body.clone(),
        StubMode::PartialStall { prefix },
        32 * 1024,
        Duration::from_millis(5),
        Duration::ZERO,
    );
    let dir = tempfile::tempdir().expect("tempdir");
    let dest = dir.path().join("Sopeek_Setup.exe");
    let (part, meta) = artifact_paths(&dest);

    let mut session = Session::spawn(&[("SPK_UPDATER_IDLE_TIMEOUT_MS", "800")]);
    session.request(
        "d1",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    session.wait_state_event("d1", "downloading", Duration::from_secs(5));
    // Once the part file holds the whole prefix, the worker has consumed every
    // byte the stub sent and is blocked in its next read.
    wait_for_part_len(&part, prefix as u64);
    thread::sleep(Duration::from_millis(150));

    session.request("p1", "pause", json!({"target": "d1"}));
    let ack = session.wait_response("p1", Duration::from_secs(5));
    assert_eq!(ack["ok"], json!(true));
    assert_eq!(ack["result"]["accepted"], json!(true));

    let started = Instant::now();
    let paused = session.wait_response("d1", Duration::from_secs(2));
    assert!(
        started.elapsed() <= Duration::from_secs(2),
        "paused terminal took {:?}",
        started.elapsed()
    );
    assert_eq!(paused["ok"], json!(true), "pause failed: {paused}");
    assert_eq!(paused["result"]["state"], json!("paused"));
    assert_eq!(paused["result"]["downloaded"], json!(prefix as u64));
    session.assert_response_count("d1", 1, "paused is exactly one terminal line");
    assert_success(session.wait_exit(Duration::from_secs(3)));

    let kept = std::fs::metadata(&part)
        .expect("part file survives pause")
        .len();
    assert!(
        kept >= prefix as u64,
        "pause must flush the received prefix, kept {kept} of {prefix}"
    );
    assert!(meta.exists(), "pause must keep the resume metadata");
}

#[test]
fn partial_body_stall_cancel_keeps_artifacts_for_service_cleanup() {
    let body = sample_body_sized(4 * MIB);
    let prefix = 512 * 1024;
    let download_stub = StubServer::start(
        body.clone(),
        StubMode::PartialStall { prefix },
        32 * 1024,
        Duration::from_millis(5),
        Duration::ZERO,
    );
    let dir = tempfile::tempdir().expect("tempdir");
    let dest = dir.path().join("Sopeek_Setup.exe");
    let (part, meta) = artifact_paths(&dest);

    let mut session = Session::spawn(&[("SPK_UPDATER_IDLE_TIMEOUT_MS", "800")]);
    session.request(
        "d1",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    session.wait_state_event("d1", "downloading", Duration::from_secs(5));
    wait_for_part_len(&part, prefix as u64);
    thread::sleep(Duration::from_millis(150));

    session.request("p1", "cancel", json!({"target": "d1"}));
    let ack = session.wait_response("p1", Duration::from_secs(5));
    assert_eq!(ack["ok"], json!(true));
    assert_eq!(ack["result"]["accepted"], json!(true));

    let started = Instant::now();
    let cancelled = session.wait_response("d1", Duration::from_secs(2));
    assert!(
        started.elapsed() <= Duration::from_secs(2),
        "cancelled terminal took {:?}",
        started.elapsed()
    );
    assert_eq!(cancelled["ok"], json!(true), "cancel failed: {cancelled}");
    assert_eq!(cancelled["result"]["state"], json!("cancelled"));
    assert_eq!(cancelled["result"]["sha256"], Value::Null);
    session.assert_response_count("d1", 1, "cancelled is exactly one terminal line");
    assert_success(session.wait_exit(Duration::from_secs(3)));

    // Plan contract: the forced-abort path never deletes artifacts that a live
    // download handle may still hold; the service layer owns that cleanup.
    assert!(
        part.exists(),
        "sidecar must leave the part file for service-side cleanup"
    );
    assert!(
        meta.exists(),
        "sidecar must leave the resume metadata for service-side cleanup"
    );
}

#[test]
fn eof_exits_without_ack_and_keeps_part_and_meta() {
    let body = sample_body();
    let download_stub = StubServer::start(
        body.clone(),
        StubMode::Stall,
        8 * 1024,
        Duration::ZERO,
        Duration::ZERO,
    );
    let dir = tempfile::tempdir().expect("tempdir");
    let dest = dir.path().join("Sopeek_Setup.exe");

    let mut session = Session::spawn(&[]);
    session.request(
        "d1",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    session.wait_state_event("d1", "downloading", Duration::from_secs(5));

    let closed_at = Instant::now();
    session.close_stdin();
    let status = session.wait_exit(Duration::from_secs(2));
    assert_success(status);
    assert!(
        closed_at.elapsed() <= Duration::from_secs(2),
        "EOF must exit within 2s, took {:?}",
        closed_at.elapsed()
    );
    session.assert_response_count(
        "d1",
        0,
        "EOF is shutdown without an ack; no terminal line may be written",
    );

    let (part, meta) = artifact_paths(&dest);
    assert!(part.exists(), "EOF must leave the part file for resume");
    assert!(meta.exists(), "EOF must leave the resume metadata");
}

#[test]
fn shutdown_joins_the_download_before_acking() {
    let body = sample_body();
    let download_stub = StubServer::start(
        body.clone(),
        StubMode::Paced,
        8 * 1024,
        Duration::from_millis(25),
        Duration::ZERO,
    );
    let dir = tempfile::tempdir().expect("tempdir");
    let dest = dir.path().join("Sopeek_Setup.exe");

    let mut session = Session::spawn(&[]);
    session.request(
        "d1",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    session.wait_state_event("d1", "downloading", Duration::from_secs(5));

    session.request("s1", "shutdown", json!({}));
    let ack = session.wait_response("s1", Duration::from_secs(5));
    assert_eq!(ack["ok"], json!(true));
    assert_success(session.wait_exit(Duration::from_secs(5)));

    let download_index = session
        .response_index("d1")
        .expect("download terminal response");
    let shutdown_index = session.response_index("s1").expect("shutdown ack");
    assert!(
        download_index < shutdown_index,
        "shutdown ack must come after the joined download terminal line"
    );

    let (part, meta) = artifact_paths(&dest);
    assert!(part.exists(), "shutdown keeps the partial download");
    assert!(meta.exists(), "shutdown keeps the resume metadata");
}

#[test]
fn shutdown_times_out_a_blocked_download_but_still_acks() {
    let body = sample_body();
    let download_stub = StubServer::start(
        body.clone(),
        StubMode::Stall,
        8 * 1024,
        Duration::ZERO,
        Duration::ZERO,
    );
    let dir = tempfile::tempdir().expect("tempdir");
    let dest = dir.path().join("Sopeek_Setup.exe");

    let mut session = Session::spawn(&[]);
    session.request(
        "d1",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    session.wait_state_event("d1", "downloading", Duration::from_secs(5));

    let started = Instant::now();
    session.request("s1", "shutdown", json!({}));
    let ack = session.wait_response("s1", Duration::from_secs(5));
    let elapsed = started.elapsed();
    assert_eq!(ack["ok"], json!(true));
    assert!(
        elapsed >= Duration::from_millis(1200),
        "shutdown must give the download up to 1.5s to flush, took {elapsed:?}"
    );
    assert!(
        elapsed < Duration::from_secs(4),
        "blocked shutdown must still finish quickly, took {elapsed:?}"
    );
    assert_success(session.wait_exit(Duration::from_secs(3)));
    assert!(
        session.response_count("d1") == 0,
        "blocked shutdown must not fabricate a paused/cancelled terminal"
    );

    let (part, meta) = artifact_paths(&dest);
    assert!(part.exists(), "blocked shutdown keeps the part file");
    assert!(meta.exists(), "blocked shutdown keeps the metadata");
}

#[test]
fn idle_watchdog_writes_timeout_error_then_exits_zero() {
    let body = sample_body();
    let download_stub = StubServer::start(
        body.clone(),
        StubMode::Stall,
        8 * 1024,
        Duration::ZERO,
        Duration::ZERO,
    );
    let dir = tempfile::tempdir().expect("tempdir");
    let dest = dir.path().join("Sopeek_Setup.exe");

    let mut session = Session::spawn(&[("SPK_UPDATER_IDLE_TIMEOUT_MS", "200")]);
    session.request(
        "d1",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    let timeout = session.wait_response("d1", Duration::from_secs(5));
    assert_eq!(timeout["ok"], json!(false));
    assert_eq!(timeout["error"]["code"], json!("timeout"));
    assert_eq!(timeout["error"]["retryable"], json!(true));
    assert_success(session.wait_exit(Duration::from_secs(3)));
    assert_eq!(session.response_count("d1"), 1, "exactly one terminal line");

    let (part, meta) = artifact_paths(&dest);
    assert!(part.exists(), "timeout keeps the part file");
    assert!(meta.exists(), "timeout keeps the resume metadata");
}

#[test]
fn graceful_pause_then_resume_resets_control_and_stalls_into_timeout() {
    let body = sample_body();
    let download_stub = StubServer::start(
        body.clone(),
        StubMode::PacedThenStall {
            paced_connections: 1,
        },
        8 * 1024,
        Duration::from_millis(20),
        Duration::ZERO,
    );
    let dir = tempfile::tempdir().expect("tempdir");
    let dest = dir.path().join("Sopeek_Setup.exe");

    let mut session = Session::spawn(&[("SPK_UPDATER_IDLE_TIMEOUT_MS", "200")]);
    session.request(
        "d1",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    session.wait_state_event("d1", "downloading", Duration::from_secs(5));

    session.request("p1", "pause", json!({"target": "d1"}));
    let ack = session.wait_response("p1", Duration::from_secs(5));
    assert_eq!(ack["result"]["accepted"], json!(true));
    let paused = session.wait_response("d1", Duration::from_secs(3));
    assert_eq!(paused["ok"], json!(true));
    assert_eq!(paused["result"]["state"], json!("paused"));
    assert_eq!(session.response_count("d1"), 1);

    // Same id in paused state resumes; the second stub connection stalls.
    session.request(
        "d1",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    let timeout = session.wait_response("d1", Duration::from_secs(5));
    assert_eq!(timeout["ok"], json!(false));
    assert_eq!(timeout["error"]["code"], json!("timeout"));
    assert_success(session.wait_exit(Duration::from_secs(3)));
    assert_eq!(
        session.response_count("d1"),
        2,
        "resume must produce exactly one new terminal line"
    );
}

#[test]
fn stale_targets_and_duplicate_active_id_do_not_disturb_the_new_download() {
    let body = sample_body();
    let download_stub = StubServer::start(
        body.clone(),
        StubMode::Paced,
        8 * 1024,
        Duration::from_millis(20),
        Duration::ZERO,
    );
    let dir = tempfile::tempdir().expect("tempdir");
    let dest = dir.path().join("Sopeek_Setup.exe");

    let mut session = Session::spawn(&[]);
    session.request(
        "d1",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    session.wait_state_event("d1", "downloading", Duration::from_secs(5));
    session.request("p1", "pause", json!({"target": "d1"}));
    let ack = session.wait_response("p1", Duration::from_secs(5));
    assert_eq!(ack["result"]["accepted"], json!(true));
    let paused = session.wait_response("d1", Duration::from_secs(5));
    assert_eq!(paused["result"]["state"], json!("paused"));

    // A different id evicts the paused request and starts a fresh download.
    session.request(
        "d2",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    session.wait_state_event("d2", "downloading", Duration::from_secs(5));

    session.request(
        "d2",
        "download",
        download_params(&download_stub, &dest, &body),
    );
    let busy = session.wait_response("d2", Duration::from_secs(5));
    assert_eq!(busy["ok"], json!(false));
    assert_eq!(busy["error"]["code"], json!("busy"));

    session.request("p2", "pause", json!({"target": "d1"}));
    let stale_pause = session.wait_response("p2", Duration::from_secs(5));
    assert_eq!(stale_pause["ok"], json!(true));
    assert_eq!(stale_pause["result"]["accepted"], json!(false));

    session.request("p3", "cancel", json!({"target": "d1"}));
    let stale_cancel = session.wait_response("p3", Duration::from_secs(5));
    assert_eq!(stale_cancel["ok"], json!(true));
    assert_eq!(stale_cancel["result"]["accepted"], json!(false));

    let done = session.wait_response("d2", Duration::from_secs(20));
    assert_eq!(
        done["ok"],
        json!(true),
        "new download was disturbed: {done}"
    );
    assert_eq!(done["result"]["state"], json!("done"));
    assert_eq!(
        std::fs::read(&dest).expect("final file"),
        body,
        "new download must complete from a clean part"
    );

    session.request("s1", "shutdown", json!({}));
    assert_eq!(
        session.wait_response("s1", Duration::from_secs(5))["ok"],
        json!(true)
    );
    assert_success(session.wait_exit(Duration::from_secs(5)));
}

#[test]
fn malformed_control_target_is_bad_params_and_writes_no_ack() {
    let mut session = Session::spawn(&[]);
    session.request("p1", "pause", json!({}));
    let missing = session.wait_response("p1", Duration::from_secs(5));
    assert_eq!(missing["ok"], json!(false));
    assert_eq!(missing["error"]["code"], json!("bad_params"));

    session.request("p2", "cancel", json!({"target": 7}));
    let wrong_type = session.wait_response("p2", Duration::from_secs(5));
    assert_eq!(wrong_type["ok"], json!(false));
    assert_eq!(wrong_type["error"]["code"], json!("bad_params"));

    session.request("s1", "shutdown", json!({}));
    assert_eq!(
        session.wait_response("s1", Duration::from_secs(5))["ok"],
        json!(true)
    );
    assert_success(session.wait_exit(Duration::from_secs(5)));
}

#[test]
fn verify_reports_match_and_rejects_bad_params() {
    let dir = tempfile::tempdir().expect("tempdir");
    let target = dir.path().join("installer.exe");
    let bytes = sample_body();
    std::fs::write(&target, &bytes).expect("write target");
    let digest = sha256_hex(&bytes);

    let mut session = Session::spawn(&[]);

    session.request(
        "v1",
        "verify",
        json!({"path": target.to_string_lossy(), "sha256": digest}),
    );
    let matched = session.wait_response("v1", Duration::from_secs(5));
    assert_eq!(matched["ok"], json!(true), "verify failed: {matched}");
    assert_eq!(matched["result"]["match"], json!(true));
    assert_eq!(matched["result"]["actual"], json!(digest));
    assert!(
        matched["result"]["volume_serial"].is_u64(),
        "verify must report the file identity volume serial"
    );
    assert!(matched["result"]["file_index"].is_u64());

    session.request(
        "v2",
        "verify",
        json!({"path": target.to_string_lossy(), "sha256": "0".repeat(64)}),
    );
    let mismatch = session.wait_response("v2", Duration::from_secs(5));
    assert_eq!(mismatch["ok"], json!(true));
    assert_eq!(mismatch["result"]["match"], json!(false));

    session.request(
        "v3",
        "verify",
        json!({"path": target.to_string_lossy(), "sha256": "not-a-hash"}),
    );
    let bad_params = session.wait_response("v3", Duration::from_secs(5));
    assert_eq!(bad_params["ok"], json!(false));
    assert_eq!(bad_params["error"]["code"], json!("bad_params"));

    session.request("s1", "shutdown", json!({}));
    assert_eq!(
        session.wait_response("s1", Duration::from_secs(5))["ok"],
        json!(true)
    );
    assert_success(session.wait_exit(Duration::from_secs(5)));
}
