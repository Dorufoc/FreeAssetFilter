//! HTTP agent configuration shared by every command.
//!
//! Two budgets are used (see plan C1):
//!
//! * `check` - tight overall budget because it is a small JSON request.
//! * `download` - no overall/body budget; a 165 MB transfer would be killed by
//!   one. Stalls are detected by [`crate::watchdog`] instead.
//!
//! Redirects and status-as-error are always disabled: the downloader validates
//! every hop itself, and HTTP error codes are mapped to protocol error codes.

use std::time::Duration;

use ureq::tls::{TlsConfig, TlsProvider};
use ureq::typestate::WithoutBody;
use ureq::{Agent, Proxy, RequestBuilder};
use url::Url;

use crate::error::{AppError, ErrorCode};

/// Sent on every request so GitHub `digest` sizes and Range offsets describe
/// the bytes on the wire.
pub const ACCEPT_ENCODING_IDENTITY: &str = "identity";

/// GitHub REST media type requested by `check`.
pub const GITHUB_ACCEPT: &str = "application/vnd.github+json";

/// Pinned GitHub REST API version requested by `check`.
pub const GITHUB_API_VERSION: &str = "2022-11-28";

/// Requested by GitHub's REST API; also identifies us in their logs.
pub const USER_AGENT: &str = concat!("FreeAssetFilter-Updater/", env!("CARGO_PKG_VERSION"));

/// Snapshot of the per-phase timeouts applied to one agent.
///
/// `None` means "no limit for this phase". Timeouts are kept as data so tests
/// can assert the exact plan values without reflecting into ureq internals.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HttpTimeouts {
    pub resolve: Option<Duration>,
    pub connect: Option<Duration>,
    pub send_request: Option<Duration>,
    pub recv_response: Option<Duration>,
    pub recv_body: Option<Duration>,
    pub global: Option<Duration>,
    pub per_call: Option<Duration>,
}

impl HttpTimeouts {
    /// Budget for `check`: 30s total, 5s DNS, 5s TCP, 10s headers, 10s body.
    pub const CHECK: Self = Self {
        resolve: Some(Duration::from_secs(5)),
        connect: Some(Duration::from_secs(5)),
        send_request: None,
        recv_response: Some(Duration::from_secs(10)),
        recv_body: Some(Duration::from_secs(10)),
        global: Some(Duration::from_secs(30)),
        per_call: None,
    };

    /// Budget for `download`: per-phase limits only, body/global unlimited.
    pub const DOWNLOAD: Self = Self {
        resolve: Some(Duration::from_secs(10)),
        connect: Some(Duration::from_secs(10)),
        send_request: Some(Duration::from_secs(30)),
        recv_response: Some(Duration::from_secs(20)),
        recv_body: None,
        global: None,
        per_call: None,
    };
}

/// Builds an agent from a timeout snapshot.
pub fn build_agent(timeouts: &HttpTimeouts) -> Agent {
    let tls = TlsConfig::builder()
        .provider(TlsProvider::NativeTls)
        .build();
    let config = Agent::config_builder()
        // The downloader follows and validates redirects itself, hop by hop.
        .max_redirects(0)
        // HTTP status codes are mapped to protocol error codes by callers.
        .http_status_as_error(false)
        .tls_config(tls)
        // Environment proxies only (no WinINET/registry auto-discovery).
        .proxy(Proxy::try_from_env())
        .user_agent(USER_AGENT)
        .timeout_global(timeouts.global)
        .timeout_resolve(timeouts.resolve)
        .timeout_connect(timeouts.connect)
        .timeout_send_request(timeouts.send_request)
        .timeout_recv_response(timeouts.recv_response)
        .timeout_recv_body(timeouts.recv_body)
        .timeout_per_call(timeouts.per_call)
        .build();
    Agent::new_with_config(config)
}

/// Agent used by `check` / `verify`-adjacent small requests.
pub fn check_agent() -> Agent {
    build_agent(&HttpTimeouts::CHECK)
}

/// Agent used by `download`.
pub fn download_agent() -> Agent {
    build_agent(&HttpTimeouts::DOWNLOAD)
}

/// Adds the headers every request must carry.
pub fn apply_common_headers(request: RequestBuilder<WithoutBody>) -> RequestBuilder<WithoutBody> {
    request.header("Accept-Encoding", ACCEPT_ENCODING_IDENTITY)
}

/// Parses `x-ratelimit-remaining`; malformed values are treated as unknown.
pub fn parse_rate_limit_remaining(value: Option<&str>) -> Option<u64> {
    value?.trim().parse().ok()
}

/// Maps a GitHub HTTP status to a protocol error, if it is not a success.
///
/// `403` is only a rate limit when GitHub explicitly reports zero remaining
/// requests; a bare `403` stays a generic `http_status`. `429` is always a rate
/// limit. All other non-2xx statuses are retryable `http_status` errors.
pub fn classify_status(status: u16, remaining: Option<u64>) -> Option<AppError> {
    if (200..300).contains(&status) {
        return None;
    }
    if status == 429 || (status == 403 && remaining == Some(0)) {
        return Some(AppError::new(
            ErrorCode::RateLimited,
            "GitHub API 请求超过速率限制，请稍后重试",
        ));
    }
    Some(AppError::new(
        ErrorCode::HttpStatus,
        format!("GitHub API 返回 HTTP {status}"),
    ))
}

/// Validates the only two accepted API bases (plan C1).
///
/// Production must use `https://api.github.com` on the default port. Tests may
/// use `http://127.0.0.1:<nonzero-port>` for a local stub. Everything else -
/// userinfo, lookalike hosts, explicit non-default ports, paths, queries,
/// fragments, other schemes - is rejected with `bad_params`.
pub fn validate_api_base(raw: &str) -> Result<String, AppError> {
    let url = Url::parse(raw.trim())
        .map_err(|error| bad_params(format!("api_base 不是合法 URL：{error}")))?;
    if !url.username().is_empty() || url.password().is_some() {
        return Err(bad_params("api_base 不能包含用户名或密码"));
    }
    if url.query().is_some() || url.fragment().is_some() || !matches!(url.path(), "" | "/") {
        return Err(bad_params("api_base 不能包含路径、查询或片段"));
    }

    match url.scheme() {
        "https" => {
            if url.host_str() != Some("api.github.com") {
                return Err(bad_params("api_base 只允许 https://api.github.com"));
            }
            if url.port().is_some() && url.port() != Some(443) {
                return Err(bad_params("api_base 只允许 GitHub 默认端口 443"));
            }
            Ok("https://api.github.com".to_owned())
        }
        "http" => {
            if url.host_str() != Some("127.0.0.1") {
                return Err(bad_params("api_base 的 http 地址只允许本机 127.0.0.1"));
            }
            let port = url
                .port()
                .ok_or_else(|| bad_params("api_base 必须显式指定非零端口"))?;
            if port == 0 {
                return Err(bad_params("api_base 端口不能为 0"));
            }
            Ok(format!("http://127.0.0.1:{port}"))
        }
        _ => Err(bad_params("api_base 只允许 https 或本机 http")),
    }
}

fn bad_params(message: impl Into<String>) -> AppError {
    AppError::new(ErrorCode::BadParams, message)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc;
    use std::thread;

    fn secs(value: u64) -> Option<Duration> {
        Some(Duration::from_secs(value))
    }

    #[test]
    fn check_timeouts_match_plan_budget() {
        let timeouts = HttpTimeouts::CHECK;
        assert_eq!(timeouts.global, secs(30));
        assert_eq!(timeouts.resolve, secs(5));
        assert_eq!(timeouts.connect, secs(5));
        assert_eq!(timeouts.recv_response, secs(10));
        assert_eq!(timeouts.recv_body, secs(10));
        assert_eq!(timeouts.send_request, None);
        assert_eq!(timeouts.per_call, None);
    }

    #[test]
    fn download_timeouts_match_plan_budget() {
        let timeouts = HttpTimeouts::DOWNLOAD;
        assert_eq!(timeouts.resolve, secs(10));
        assert_eq!(timeouts.connect, secs(10));
        assert_eq!(timeouts.send_request, secs(30));
        assert_eq!(timeouts.recv_response, secs(20));
        assert_eq!(timeouts.recv_body, None);
        assert_eq!(timeouts.global, None);
        assert_eq!(timeouts.per_call, None);
    }

    #[test]
    fn agent_disables_redirects_and_status_errors_and_pins_native_tls() {
        let agent = build_agent(&HttpTimeouts::CHECK);
        let config = agent.config();
        assert_eq!(config.max_redirects(), 0, "redirects must be manual");
        assert!(
            !config.http_status_as_error(),
            "HTTP status codes are mapped by protocol logic"
        );
        assert_eq!(config.tls_config().provider(), TlsProvider::NativeTls);
    }

    #[test]
    fn every_request_carries_identity_accept_encoding() {
        let server = tiny_http::Server::http("127.0.0.1:0").expect("start stub server");
        let addr = server.server_addr().to_ip().expect("loopback address");
        let (tx, rx) = mpsc::channel();

        let server_thread = thread::spawn(move || {
            let request = server.recv().expect("receive request");
            let encoding = request
                .headers()
                .iter()
                .find(|header| header.field.equiv("Accept-Encoding"))
                .map(|header| header.value.as_str().to_owned());
            tx.send(encoding).ok();
            request
                .respond(tiny_http::Response::from_string("ok"))
                .expect("respond");
        });

        let agent = build_agent(&HttpTimeouts::CHECK);
        let response = apply_common_headers(agent.get(format!("http://{addr}/")))
            .call()
            .expect("stub request");
        assert_eq!(response.status().as_u16(), 200);

        let encoding = rx
            .recv_timeout(Duration::from_secs(5))
            .expect("header seen");
        server_thread.join().expect("server thread");
        assert_eq!(encoding.as_deref(), Some(ACCEPT_ENCODING_IDENTITY));
    }

    #[test]
    fn check_status_mapping_separates_rate_limits_from_server_errors() {
        assert!(classify_status(200, None).is_none());
        assert!(classify_status(204, None).is_none());

        let limited = classify_status(403, Some(0)).expect("403 with zero remaining");
        assert_eq!(limited.code, ErrorCode::RateLimited);
        assert!(limited.body().retryable);

        let limited = classify_status(429, Some(0)).expect("429");
        assert_eq!(limited.code, ErrorCode::RateLimited);
        assert!(limited.body().retryable);

        let limited = classify_status(429, None).expect("429 without the header");
        assert_eq!(limited.code, ErrorCode::RateLimited);

        let forbidden = classify_status(403, Some(12)).expect("plain 403");
        assert_eq!(forbidden.code, ErrorCode::HttpStatus);
        assert!(forbidden.body().retryable);

        let server = classify_status(500, None).expect("500");
        assert_eq!(server.code, ErrorCode::HttpStatus);
        assert!(server.body().retryable);
        assert!(server.message.contains("500"));

        let missing = classify_status(404, None).expect("404");
        assert_eq!(missing.code, ErrorCode::HttpStatus);
    }

    #[test]
    fn check_rate_limit_header_parsing_is_lenient() {
        assert_eq!(parse_rate_limit_remaining(Some("0")), Some(0));
        assert_eq!(parse_rate_limit_remaining(Some(" 12 ")), Some(12));
        assert_eq!(parse_rate_limit_remaining(Some("")), None);
        assert_eq!(parse_rate_limit_remaining(Some("abc")), None);
        assert_eq!(parse_rate_limit_remaining(None), None);
    }

    #[test]
    fn check_api_base_accepts_only_pinned_github_or_loopback() {
        for accepted in [
            "https://api.github.com",
            "https://api.github.com/",
            "https://api.github.com:443",
            "http://127.0.0.1:18080",
        ] {
            let base = validate_api_base(accepted).expect(accepted);
            assert!(!base.ends_with('/'), "{accepted} must be normalized");
        }

        for rejected in [
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
            "https://api.github.com#frag",
        ] {
            let error = validate_api_base(rejected).expect_err(rejected);
            assert_eq!(error.code, ErrorCode::BadParams, "{rejected}");
        }
    }
}
