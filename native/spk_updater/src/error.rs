//! Fixed error-code enum and typed error payload shared by every command.
//!
//! The wire format is defined by the updater plan (C1): every failure response
//! is `{"id":...,"ok":false,"error":{"code":...,"message":...,"retryable":...}}`
//! and `code` is one of the nineteen variants below.

use std::fmt;

use serde::{Deserialize, Serialize};

/// Closed set of protocol error codes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    BadCommand,
    BadParams,
    BadRange,
    Busy,
    ChecksumMismatch,
    ChecksumMissing,
    Cancelled,
    HttpStatus,
    Io,
    InvalidJson,
    InvalidVersion,
    Network,
    NoInstallerAsset,
    NoRelease,
    RateLimited,
    SizeMismatch,
    Timeout,
    UnsafeUrl,
    Internal,
}

impl ErrorCode {
    /// Stable snake_case wire name.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::BadCommand => "bad_command",
            Self::BadParams => "bad_params",
            Self::BadRange => "bad_range",
            Self::Busy => "busy",
            Self::ChecksumMismatch => "checksum_mismatch",
            Self::ChecksumMissing => "checksum_missing",
            Self::Cancelled => "cancelled",
            Self::HttpStatus => "http_status",
            Self::Io => "io",
            Self::InvalidJson => "invalid_json",
            Self::InvalidVersion => "invalid_version",
            Self::Network => "network",
            Self::NoInstallerAsset => "no_installer_asset",
            Self::NoRelease => "no_release",
            Self::RateLimited => "rate_limited",
            Self::SizeMismatch => "size_mismatch",
            Self::Timeout => "timeout",
            Self::UnsafeUrl => "unsafe_url",
            Self::Internal => "internal",
        }
    }

    /// Whether the caller may retry the same operation unchanged.
    ///
    /// Only transient transport/backpressure codes are retryable.
    pub fn retryable(self) -> bool {
        matches!(
            self,
            Self::Network | Self::HttpStatus | Self::RateLimited | Self::Timeout | Self::Busy
        )
    }
}

impl fmt::Display for ErrorCode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Serialized error object carried by a failure response.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ErrorBody {
    pub code: ErrorCode,
    pub message: String,
    pub retryable: bool,
}

/// Internal error value used across modules.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AppError {
    pub code: ErrorCode,
    pub message: String,
}

impl AppError {
    /// Creates an error with a Chinese diagnostic message.
    pub fn new(code: ErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    /// Serializes this error into the protocol envelope payload.
    pub fn body(&self) -> ErrorBody {
        ErrorBody {
            code: self.code,
            message: self.message.clone(),
            retryable: self.code.retryable(),
        }
    }
}

impl fmt::Display for AppError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for AppError {}

#[cfg(test)]
mod tests {
    use super::*;

    const ALL: [ErrorCode; 19] = [
        ErrorCode::BadCommand,
        ErrorCode::BadParams,
        ErrorCode::BadRange,
        ErrorCode::Busy,
        ErrorCode::ChecksumMismatch,
        ErrorCode::ChecksumMissing,
        ErrorCode::Cancelled,
        ErrorCode::HttpStatus,
        ErrorCode::Io,
        ErrorCode::InvalidJson,
        ErrorCode::InvalidVersion,
        ErrorCode::Network,
        ErrorCode::NoInstallerAsset,
        ErrorCode::NoRelease,
        ErrorCode::RateLimited,
        ErrorCode::SizeMismatch,
        ErrorCode::Timeout,
        ErrorCode::UnsafeUrl,
        ErrorCode::Internal,
    ];

    #[test]
    fn error_codes_serialize_to_plan_names() {
        let expected = [
            "bad_command",
            "bad_params",
            "bad_range",
            "busy",
            "checksum_mismatch",
            "checksum_missing",
            "cancelled",
            "http_status",
            "io",
            "invalid_json",
            "invalid_version",
            "network",
            "no_installer_asset",
            "no_release",
            "rate_limited",
            "size_mismatch",
            "timeout",
            "unsafe_url",
            "internal",
        ];
        for (code, name) in ALL.iter().zip(expected) {
            assert_eq!(code.as_str(), name);
            assert_eq!(
                serde_json::to_value(code).expect("serialize"),
                serde_json::Value::String(name.to_owned())
            );
        }
    }

    #[test]
    fn retryable_is_limited_to_transient_codes() {
        let retryable = [
            ErrorCode::Network,
            ErrorCode::HttpStatus,
            ErrorCode::RateLimited,
            ErrorCode::Timeout,
            ErrorCode::Busy,
        ];
        for code in ALL {
            assert_eq!(code.retryable(), retryable.contains(&code), "{code}");
        }
    }

    #[test]
    fn error_body_carries_retryable_flag() {
        let err = AppError::new(ErrorCode::Network, "网络连接失败");
        assert_eq!(
            serde_json::to_value(err.body()).expect("serialize"),
            serde_json::json!({
                "code": "network",
                "message": "网络连接失败",
                "retryable": true
            })
        );
    }

    #[test]
    fn non_retryable_body_is_marked_false() {
        let err = AppError::new(ErrorCode::UnsafeUrl, "不安全的下载地址");
        assert!(!err.body().retryable);
        assert_eq!(err.code, ErrorCode::UnsafeUrl);
        assert!(err.to_string().contains("unsafe_url"));
    }
}
