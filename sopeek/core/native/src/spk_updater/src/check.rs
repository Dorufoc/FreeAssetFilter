//! `check` command: fetch the GitHub release list and produce the C1 result.
//!
//! Network access is pinned to [`crate::http::check_agent`] (30s global budget)
//! and the base URL is validated by [`crate::http::validate_api_base`], so a
//! hostile `api_base` can never redirect the request to another host.

use serde_json::{json, Map, Value};

use crate::error::{AppError, ErrorCode};
use crate::http::{
    apply_common_headers, check_agent, classify_status, parse_rate_limit_remaining,
    validate_api_base, GITHUB_ACCEPT, GITHUB_API_VERSION,
};
use crate::release;
use crate::version::evaluate_update;

/// GitHub's maximum page size; the updater only needs the newest releases.
const RELEASES_PER_PAGE: u32 = 30;

/// Validated `check` parameters (plan C1).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CheckParams {
    pub repo: String,
    pub current_version: String,
    pub current_date: Option<String>,
    pub include_prerelease: bool,
    pub api_base: String,
}

impl CheckParams {
    /// Parses and validates the raw `params` object.
    ///
    /// Unknown fields are ignored. `repo` and `current_version` are required;
    /// `current_date` defaults to `None`, `include_prerelease` to `false`, and
    /// `api_base` to the pinned GitHub endpoint.
    pub fn from_value(value: &Value) -> Result<Self, AppError> {
        let object = value
            .as_object()
            .ok_or_else(|| bad_params("check 参数必须是 JSON 对象"))?;
        let repo = required_string(object, "repo")?;
        validate_repo(&repo)?;
        let current_version = required_string(object, "current_version")?;

        let current_date = match object.get("current_date") {
            None | Some(Value::Null) => None,
            Some(Value::String(date)) => Some(date.clone()),
            Some(_) => return Err(bad_params("current_date 必须是字符串或 null")),
        };
        let include_prerelease = match object.get("include_prerelease") {
            None => false,
            Some(Value::Bool(flag)) => *flag,
            Some(_) => return Err(bad_params("include_prerelease 必须是布尔值")),
        };
        let api_base = match object.get("api_base") {
            None | Some(Value::Null) => validate_api_base("https://api.github.com")?,
            Some(Value::String(base)) => validate_api_base(base)?,
            Some(_) => return Err(bad_params("api_base 必须是字符串")),
        };

        Ok(Self {
            repo,
            current_version,
            current_date,
            include_prerelease,
            api_base,
        })
    }
}

/// Executes `check` and returns the exact C1 result object.
///
/// The request is bounded by [`check_agent`]'s 30s global timeout. HTTP status
/// codes are classified before the body is parsed, so rate limits and server
/// errors never surface as JSON errors.
pub fn execute_check(params: &CheckParams) -> Result<Value, AppError> {
    let (owner, repository) = params
        .repo
        .split_once('/')
        .ok_or_else(|| bad_params("repo 必须是 owner/name 形式"))?;
    let url = format!(
        "{}/repos/{owner}/{repository}/releases?per_page={RELEASES_PER_PAGE}",
        params.api_base
    );

    let agent = check_agent();
    let request = apply_common_headers(agent.get(&url))
        .header("Accept", GITHUB_ACCEPT)
        .header("X-GitHub-Api-Version", GITHUB_API_VERSION);
    let mut response = request.call().map_err(map_transport_error)?;

    let status = response.status().as_u16();
    let remaining = response
        .headers()
        .get("x-ratelimit-remaining")
        .and_then(|value| value.to_str().ok())
        .map(str::to_owned);
    if let Some(error) = classify_status(status, parse_rate_limit_remaining(remaining.as_deref())) {
        return Err(error);
    }

    let body = response
        .body_mut()
        .read_to_string()
        .map_err(map_transport_error)?;
    let selected = release::resolve_releases(&body, params.include_prerelease)?;
    let decision = evaluate_update(
        &params.current_version,
        params.current_date.as_deref(),
        &selected.remote.version,
        selected.remote.date.as_deref(),
    )?;

    Ok(json!({
        "update_available": decision.update_available,
        "reason": decision.reason.as_str(),
        "skipped_newer_tag": selected.skipped_newer_tag,
        "local": {
            "version": params.current_version,
            "date": params.current_date,
        },
        "remote": selected.remote,
        "asset": selected.asset,
    }))
}

fn required_string(object: &Map<String, Value>, field: &str) -> Result<String, AppError> {
    match object.get(field) {
        Some(Value::String(value)) if !value.trim().is_empty() => Ok(value.trim().to_owned()),
        Some(Value::String(_)) => Err(bad_params(format!("{field} 不能为空"))),
        Some(_) => Err(bad_params(format!("{field} 必须是字符串"))),
        None => Err(bad_params(format!("缺少必填参数 {field}"))),
    }
}

/// Accepts exactly `owner/name` with GitHub-safe characters.
///
/// This is a URL-path guard, not a GitHub naming validator: it prevents a
/// caller from injecting extra path segments or query strings into the request.
fn validate_repo(repo: &str) -> Result<(), AppError> {
    let mut parts = repo.split('/');
    let owner = parts.next().unwrap_or_default();
    let repository = parts.next().unwrap_or_default();
    if parts.next().is_some() || !is_repo_segment(owner) || !is_repo_segment(repository) {
        return Err(bad_params("repo 必须是 owner/name 形式"));
    }
    Ok(())
}

fn is_repo_segment(segment: &str) -> bool {
    !segment.is_empty()
        && segment != "."
        && segment != ".."
        && segment.chars().all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '-' | '_' | '.')
        })
}

fn map_transport_error(error: ureq::Error) -> AppError {
    match error {
        ureq::Error::Timeout(_) => AppError::new(ErrorCode::Timeout, "检查更新超时（30 秒）"),
        ureq::Error::BadUri(message) => AppError::new(
            ErrorCode::BadParams,
            format!("api_base 请求地址无效：{message}"),
        ),
        other => AppError::new(ErrorCode::Network, format!("检查更新失败：{other}")),
    }
}

fn bad_params(message: impl Into<String>) -> AppError {
    AppError::new(ErrorCode::BadParams, message)
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::PathBuf;
    use std::sync::mpsc;
    use std::thread;
    use std::time::Duration;

    use serde_json::{json, Value};
    use tiny_http::{Header, Response as StubResponse, Server};

    use super::*;
    use crate::error::ErrorCode;

    const REPO: &str = "Dorufoc/Sopeek";

    struct CapturedRequest {
        method: String,
        url: String,
        headers: Vec<(String, String)>,
    }

    impl CapturedRequest {
        fn header(&self, name: &str) -> Option<&str> {
            self.headers
                .iter()
                .find(|(field, _)| field.eq_ignore_ascii_case(name))
                .map(|(_, value)| value.as_str())
        }
    }

    fn params_value(api_base: &str, include_prerelease: bool) -> Value {
        json!({
            "repo": REPO,
            "current_version": "1.0.0-alpha.5",
            "current_date": "2026-05-22",
            "include_prerelease": include_prerelease,
            "api_base": api_base,
        })
    }

    fn params(api_base: &str, include_prerelease: bool) -> CheckParams {
        CheckParams::from_value(&params_value(api_base, include_prerelease)).expect("valid params")
    }

    fn fixture_value() -> Value {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../../../../tests/fixtures/releases.json");
        let text = fs::read_to_string(&path)
            .unwrap_or_else(|error| panic!("read fixture {}: {error}", path.display()));
        serde_json::from_str(&text).expect("parse fixture JSON")
    }

    /// Serializes the named fixture releases back into a GitHub-shaped body.
    fn fixture_body(tags: &[&str]) -> String {
        let all = fixture_value();
        let releases = all.as_array().expect("fixture is an array");
        let selected: Vec<Value> = tags
            .iter()
            .map(|tag| {
                releases
                    .iter()
                    .find(|release| release["tag_name"] == Value::String((*tag).to_owned()))
                    .unwrap_or_else(|| panic!("fixture is missing tag {tag}"))
                    .clone()
            })
            .collect();
        serde_json::to_string(&selected).expect("serialize fixture subset")
    }

    fn start_stub(
        status: u16,
        body: String,
        headers: Vec<(&'static str, &'static str)>,
    ) -> (
        String,
        mpsc::Receiver<CapturedRequest>,
        thread::JoinHandle<()>,
    ) {
        let server = Server::http("127.0.0.1:0").expect("start stub server");
        let addr = server.server_addr().to_ip().expect("loopback address");
        let (tx, rx) = mpsc::channel();
        let handle = thread::spawn(move || {
            // Bounded wait: a failing check may never reach the stub, and an
            // unbounded `recv()` would hang the test suite instead of failing.
            let Ok(Some(request)) = server.recv_timeout(Duration::from_secs(5)) else {
                return;
            };
            let captured = CapturedRequest {
                method: request.method().as_str().to_owned(),
                url: request.url().to_owned(),
                headers: request
                    .headers()
                    .iter()
                    .map(|header| {
                        (
                            header.field.to_string().to_ascii_lowercase(),
                            header.value.as_str().to_owned(),
                        )
                    })
                    .collect(),
            };
            tx.send(captured).ok();

            let mut response = StubResponse::from_string(body).with_status_code(status);
            for (name, value) in headers {
                response = response.with_header(
                    Header::from_bytes(name.as_bytes(), value.as_bytes()).expect("stub header"),
                );
            }
            request.respond(response).expect("respond");
        });
        (format!("http://{addr}"), rx, handle)
    }

    #[test]
    fn happy_path_returns_full_c1_result_and_required_headers() {
        let body = fixture_body(&["v1.0.0-alpha.6", "v1.0.0-alpha.9"]);
        let (base, rx, handle) = start_stub(200, body, Vec::new());

        let result = execute_check(&params(&base, true)).expect("check succeeds");

        let captured = rx
            .recv_timeout(Duration::from_secs(5))
            .expect("stub received the request");
        handle.join().expect("stub thread");

        assert_eq!(captured.method, "GET");
        assert_eq!(
            captured.url,
            "/repos/Dorufoc/Sopeek/releases?per_page=30"
        );
        assert_eq!(
            captured.header("Accept"),
            Some("application/vnd.github+json")
        );
        assert_eq!(captured.header("X-GitHub-Api-Version"), Some("2022-11-28"));
        assert_eq!(captured.header("Accept-Encoding"), Some("identity"));
        assert!(
            !captured.header("User-Agent").unwrap_or("").is_empty(),
            "the request must identify the updater"
        );

        assert_eq!(result["update_available"], json!(true));
        assert_eq!(result["reason"], json!("newer_version"));
        assert_eq!(result["skipped_newer_tag"], Value::Null);
        assert_eq!(
            result["local"],
            json!({"version": "1.0.0-alpha.5", "date": "2026-05-22"})
        );

        assert_eq!(result["remote"]["version"], json!("1.0.0-alpha.9"));
        assert_eq!(result["remote"]["tag"], json!("v1.0.0-alpha.9"));
        assert_eq!(result["remote"]["date"], json!("2026-06-02"));
        assert_eq!(
            result["remote"]["published_at"],
            json!("2026-06-03T02:03:04Z")
        );
        assert_eq!(result["remote"]["prerelease"], json!(true));
        assert_eq!(
            result["remote"]["html_url"],
            json!("https://github.com/Dorufoc/Sopeek/releases/tag/v1.0.0-alpha.9")
        );
        assert_eq!(
            result["remote"]["notes"],
            json!("构建日期: 2026-06-02\n\n预发布版本 alpha.9。")
        );
        assert_eq!(result["remote"]["notes_truncated"], json!(false));

        assert_eq!(
            result["asset"]["name"],
            json!("Sopeek-1.0.0-alpha.9_win10_win11_x64_Setup.exe")
        );
        assert_eq!(result["asset"]["size"], json!(171_000_000_u64));
        assert_eq!(
            result["asset"]["sha256"],
            json!("abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789")
        );
        assert_eq!(
            result["asset"]["download_url"],
            json!("https://github.com/Dorufoc/Sopeek/releases/download/v1.0.0-alpha.9/Sopeek-1.0.0-alpha.9_win10_win11_x64_Setup.exe")
        );
    }

    #[test]
    fn skipped_newer_tag_reports_newest_release_without_installer() {
        let body = fixture_body(&["v1.0.0-alpha.6", "v1.0.0-alpha.7"]);
        let (base, rx, handle) = start_stub(200, body, Vec::new());

        let result = execute_check(&params(&base, true)).expect("check succeeds");

        let _ = rx.recv_timeout(Duration::from_secs(5));
        handle.join().expect("stub thread");
        assert_eq!(result["remote"]["version"], json!("1.0.0-alpha.6"));
        assert_eq!(result["skipped_newer_tag"], json!("v1.0.0-alpha.7"));
    }

    #[test]
    fn forbidden_with_exhausted_rate_limit_is_rate_limited() {
        let (base, _, handle) = start_stub(
            403,
            r#"{"message":"API rate limit exceeded"}"#.to_owned(),
            vec![("x-ratelimit-remaining", "0")],
        );

        let error = execute_check(&params(&base, true)).expect_err("must fail");

        handle.join().expect("stub thread");
        assert_eq!(error.code, ErrorCode::RateLimited);
        assert!(error.body().retryable);
        assert!(error.message.contains("速率限制"));
    }

    #[test]
    fn too_many_requests_with_zero_remaining_is_rate_limited() {
        let (base, _, handle) = start_stub(
            429,
            r#"{"message":"slow down"}"#.to_owned(),
            vec![("x-ratelimit-remaining", "0")],
        );

        let error = execute_check(&params(&base, true)).expect_err("must fail");

        handle.join().expect("stub thread");
        assert_eq!(error.code, ErrorCode::RateLimited);
        assert!(error.body().retryable);
    }

    #[test]
    fn server_error_is_retryable_http_status() {
        let (base, _, handle) = start_stub(500, "internal error".to_owned(), Vec::new());

        let error = execute_check(&params(&base, true)).expect_err("must fail");

        handle.join().expect("stub thread");
        assert_eq!(error.code, ErrorCode::HttpStatus);
        assert!(error.body().retryable);
        assert!(error.message.contains("500"));
    }

    #[test]
    fn malformed_release_json_is_invalid_json() {
        let (base, _, handle) = start_stub(200, "{not json".to_owned(), Vec::new());

        let error = execute_check(&params(&base, true)).expect_err("must fail");

        handle.join().expect("stub thread");
        assert_eq!(error.code, ErrorCode::InvalidJson);
        assert!(!error.body().retryable);
    }

    #[test]
    fn hostile_api_bases_are_rejected_as_bad_params() {
        for api_base in [
            "",
            "not a url",
            "https://api.github.com.evil.com",
            "https://api.github.com@evil.com",
            "https://user:pass@api.github.com",
            "http://api.github.com",
            "https://127.0.0.1:18080",
            "https://api.github.com:8443",
            "http://127.0.0.1:0",
            "http://127.0.0.1",
            "ftp://api.github.com",
            "https://api.github.com/evil",
            "https://api.github.com?x=1",
        ] {
            let error = CheckParams::from_value(&params_value(api_base, true))
                .expect_err("hostile api_base must be rejected");
            assert_eq!(error.code, ErrorCode::BadParams, "{api_base}");
        }
    }

    #[test]
    fn api_base_accepts_pinned_github_and_loopback_ports() {
        for api_base in [
            "https://api.github.com",
            "https://api.github.com/",
            "https://api.github.com:443",
            "http://127.0.0.1:18080",
        ] {
            let parsed = CheckParams::from_value(&params_value(api_base, true))
                .unwrap_or_else(|error| panic!("{api_base} must be accepted: {error}"));
            assert!(
                !parsed.api_base.ends_with('/'),
                "{api_base} must be normalized without a trailing slash"
            );
        }
    }

    #[test]
    fn unknown_params_fields_are_ignored_and_optional_fields_default() {
        let value = json!({
            "repo": REPO,
            "current_version": "1.0.0-alpha.5",
            "include_prerelease": true,
            "api_base": "https://api.github.com",
            "extra": {"nested": [1, 2, 3]},
        });

        let parsed = CheckParams::from_value(&value).expect("unknown fields ignored");
        assert_eq!(parsed.current_date, None);
    }

    #[test]
    fn missing_current_version_and_malformed_repo_are_bad_params() {
        let missing = json!({
            "repo": REPO,
            "include_prerelease": true,
            "api_base": "https://api.github.com",
        });
        assert_eq!(
            CheckParams::from_value(&missing).unwrap_err().code,
            ErrorCode::BadParams
        );

        for repo in [
            "",
            "Dorufoc",
            "Dorufoc/Sopeek/extra",
            "../x",
            "Dorufoc/Sopeek repo",
            "Dorufoc/../x",
        ] {
            let value = json!({
                "repo": repo,
                "current_version": "1.0.0-alpha.5",
                "include_prerelease": true,
                "api_base": "https://api.github.com",
            });
            assert_eq!(
                CheckParams::from_value(&value).unwrap_err().code,
                ErrorCode::BadParams,
                "{repo}"
            );
        }
    }

    #[test]
    fn protocol_check_command_dispatches_to_check() {
        let body = fixture_body(&["v1.0.0-alpha.6"]);
        let (base, rx, handle) = start_stub(200, body, Vec::new());
        let line = json!({
            "id": "c7",
            "cmd": "check",
            "params": params_value(&base, true),
        })
        .to_string();

        let response = crate::protocol::handle_line(&line).expect("response");

        let _ = rx.recv_timeout(Duration::from_secs(5));
        handle.join().expect("stub thread");
        assert!(response.ok);
        assert_eq!(response.id, "c7");
        assert_eq!(
            response.result.expect("result")["reason"],
            json!("newer_version")
        );
    }

    #[test]
    fn protocol_check_with_bad_params_reports_bad_params() {
        let response = crate::protocol::handle_line(
            r#"{"id":"c8","cmd":"check","params":{"repo":"Dorufoc/Sopeek"}}"#,
        )
        .expect("response");

        assert!(!response.ok);
        assert_eq!(response.id, "c8");
        assert_eq!(response.error.expect("error").code, ErrorCode::BadParams);
    }
}
