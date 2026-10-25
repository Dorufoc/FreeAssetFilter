//! NDJSON protocol types and the TODO-1 command dispatcher.
//!
//! One JSON object per line on stdin/stdout, UTF-8. Requests carry a
//! caller-generated `id` which is echoed verbatim on the matching response.
//! TODO 1 only implements `hello`; every other command name is answered with
//! `bad_command` until its owning todo lands.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::error::{AppError, ErrorBody, ErrorCode};

/// Wire protocol revision advertised by `hello`.
pub const PROTOCOL_VERSION: u32 = 1;

/// Incoming command line.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Request {
    pub id: String,
    pub cmd: String,
    /// Command-specific payload. Kept as a raw value so unknown fields are
    /// ignored instead of rejected.
    #[serde(default)]
    pub params: Value,
}

/// Response envelope shared by success and failure replies.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Response {
    pub id: String,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<ErrorBody>,
}

impl Response {
    /// Successful envelope.
    pub fn success(id: impl Into<String>, result: Value) -> Self {
        Self {
            id: id.into(),
            ok: true,
            result: Some(result),
            error: None,
        }
    }

    /// Failure envelope.
    pub fn failure(id: impl Into<String>, err: &AppError) -> Self {
        Self {
            id: id.into(),
            ok: false,
            result: None,
            error: Some(err.body()),
        }
    }
}

/// Result payload of the `hello` command.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HelloResult {
    pub protocol: u32,
    pub version: String,
}

impl HelloResult {
    /// Current process identity, ready to embed in a response envelope.
    pub fn current() -> Self {
        Self {
            protocol: PROTOCOL_VERSION,
            version: env!("CARGO_PKG_VERSION").to_owned(),
        }
    }

    /// Converts to a JSON object without a fallible serializer.
    fn into_value(self) -> Value {
        json!({"protocol": self.protocol, "version": self.version})
    }
}

/// Download lifecycle states carried by `state` events.
#[allow(dead_code)] // emitted by the download state machine (TODO 4/5).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DownloadState {
    Resolving,
    Downloading,
    Paused,
    Verifying,
    Done,
    Cancelled,
}

/// Asynchronous event emitted while a download is in flight.
#[allow(dead_code)] // emitted by the download state machine (TODO 4/5).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum Event {
    Progress {
        id: String,
        downloaded: u64,
        total: u64,
        speed_bps: u64,
    },
    State {
        id: String,
        state: DownloadState,
    },
}

/// Parses one non-empty request line.
pub fn parse_request(line: &str) -> Result<Request, AppError> {
    serde_json::from_str::<Request>(line).map_err(|error| {
        AppError::new(
            ErrorCode::InvalidJson,
            format!("无法解析请求 JSON：{error}"),
        )
    })
}

/// Handles one stdin line.
///
/// Returns `None` for blank lines (nothing is written) and a failure envelope
/// for malformed JSON so the process keeps serving subsequent commands.
pub fn handle_line(line: &str) -> Option<Response> {
    if line.trim().is_empty() {
        return None;
    }
    let response = match parse_request(line) {
        Ok(request) => dispatch(request),
        // No usable id exists for unparseable input; the bridge keys its
        // timeout handling on the request it sent, not on this reply.
        Err(error) => Response::failure(String::new(), &error),
    };
    Some(response)
}

/// Dispatches a parsed request.
pub fn dispatch(request: Request) -> Response {
    let id = request.id;
    match request.cmd.as_str() {
        "hello" => Response::success(id, HelloResult::current().into_value()),
        "check" => match crate::check::CheckParams::from_value(&request.params) {
            Ok(params) => match crate::check::execute_check(&params) {
                Ok(result) => Response::success(id, result),
                Err(error) => Response::failure(id, &error),
            },
            Err(error) => Response::failure(id, &error),
        },
        other => Response::failure(
            id,
            &AppError::new(ErrorCode::BadCommand, format!("未知命令：{other}")),
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_roundtrip_preserves_fields() {
        let line = r#"{"id":"c1","cmd":"hello","params":{}}"#;
        let request = parse_request(line).expect("parse");
        assert_eq!(request.id, "c1");
        assert_eq!(request.cmd, "hello");
        assert_eq!(
            serde_json::to_value(&request).expect("serialize"),
            serde_json::json!({"id": "c1", "cmd": "hello", "params": {}})
        );
    }

    #[test]
    fn request_without_params_defaults_to_null() {
        let request = parse_request(r#"{"id":"c7","cmd":"hello"}"#).expect("parse");
        assert_eq!(request.params, Value::Null);
    }

    #[test]
    fn hello_returns_protocol_one_and_crate_version() {
        let response = handle_line(r#"{"id":"c1","cmd":"hello","params":{}}"#).expect("response");
        assert!(response.ok);
        assert_eq!(response.id, "c1");
        let result = response.result.expect("result");
        assert_eq!(result["protocol"], json!(1));
        assert_eq!(result["version"], json!(env!("CARGO_PKG_VERSION")));
        assert!(response.error.is_none());
    }

    #[test]
    fn unknown_command_returns_bad_command_and_echoes_id() {
        let response =
            handle_line(r#"{"id":"c9","cmd":"frobnicate","params":{}}"#).expect("response");
        assert!(!response.ok);
        assert_eq!(response.id, "c9");
        assert_eq!(
            response.error.as_ref().map(|e| e.code),
            Some(ErrorCode::BadCommand)
        );
        assert!(response.result.is_none());
    }

    #[test]
    fn invalid_json_returns_invalid_json_and_process_continues() {
        let bad = handle_line("{definitely not json").expect("response");
        assert!(!bad.ok);
        assert_eq!(
            bad.error.as_ref().map(|e| e.code),
            Some(ErrorCode::InvalidJson)
        );

        let good = handle_line(r#"{"id":"c2","cmd":"hello","params":{}}"#).expect("response");
        assert!(good.ok, "process must keep serving after a bad line");
        assert_eq!(good.id, "c2");
    }

    #[test]
    fn blank_lines_produce_no_response() {
        assert!(handle_line("").is_none());
        assert!(handle_line("   \t ").is_none());
    }

    #[test]
    fn id_is_echoed_exactly() {
        let id = "c42-with spaces-✓";
        let line = format!(r#"{{"id":"{id}","cmd":"hello","params":{{}}}}"#);
        let response = handle_line(&line).expect("response");
        assert_eq!(response.id, id);
    }

    #[test]
    fn unknown_params_fields_are_ignored() {
        let response = handle_line(
            r#"{"id":"c3","cmd":"hello","params":{"unexpected":true,"nested":{"x":1}}}"#,
        )
        .expect("response");
        assert!(response.ok, "unknown params must not fail the command");
    }

    #[test]
    fn success_envelope_matches_contract_shape() {
        let response = handle_line(r#"{"id":"c1","cmd":"hello","params":{}}"#).expect("response");
        let value = serde_json::to_value(&response).expect("serialize");
        assert_eq!(
            value,
            json!({
                "id": "c1",
                "ok": true,
                "result": {"protocol": 1, "version": env!("CARGO_PKG_VERSION")}
            })
        );
    }

    #[test]
    fn failure_envelope_matches_contract_shape() {
        let response = handle_line(r#"{"id":"c4","cmd":"nope"}"#).expect("response");
        let value = serde_json::to_value(&response).expect("serialize");
        assert_eq!(value["id"], json!("c4"));
        assert_eq!(value["ok"], json!(false));
        assert_eq!(value["error"]["code"], json!("bad_command"));
        assert_eq!(value["error"]["retryable"], json!(false));
        assert!(value["error"]["message"].is_string());
        assert!(value.get("result").is_none());
    }

    #[test]
    fn progress_and_state_events_match_contract() {
        let progress = Event::Progress {
            id: "c5".to_owned(),
            downloaded: 1024,
            total: 2048,
            speed_bps: 512,
        };
        assert_eq!(
            serde_json::to_value(&progress).expect("serialize"),
            json!({
                "event": "progress",
                "id": "c5",
                "downloaded": 1024,
                "total": 2048,
                "speed_bps": 512
            })
        );

        let state = Event::State {
            id: "c5".to_owned(),
            state: DownloadState::Verifying,
        };
        assert_eq!(
            serde_json::to_value(&state).expect("serialize"),
            json!({"event": "state", "id": "c5", "state": "verifying"})
        );
        for (state, name) in [
            (DownloadState::Resolving, "resolving"),
            (DownloadState::Downloading, "downloading"),
            (DownloadState::Paused, "paused"),
            (DownloadState::Verifying, "verifying"),
            (DownloadState::Done, "done"),
            (DownloadState::Cancelled, "cancelled"),
        ] {
            assert_eq!(
                serde_json::to_value(state).expect("serialize"),
                Value::String(name.to_owned())
            );
        }
    }
}
