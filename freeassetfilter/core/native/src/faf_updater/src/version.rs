//! Version parsing, semver ordering and update decisions (plan C2).
//!
//! Pure functions only: no I/O and no network. The `check` command
//! consumes these to compare the local `FAFVERSION` against a GitHub tag.

use std::cmp::Ordering;

use chrono::NaiveDate;
use semver::Version;

use crate::error::{AppError, ErrorCode};

/// Update verdict carried by `check.result.reason`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UpdateReason {
    /// The remote semver is strictly newer than the local version.
    NewerVersion,
    /// Same semver but the remote build date is later (a rebuild).
    Rebuild,
    /// The local semver is strictly newer than the remote one.
    LocalNewer,
    /// Nothing to do: equal versions/dates or an incomparable local date.
    None,
}

impl UpdateReason {
    /// Stable snake_case wire name used by `check.result.reason`.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::NewerVersion => "newer_version",
            Self::Rebuild => "rebuild",
            Self::LocalNewer => "local_newer",
            Self::None => "none",
        }
    }

    /// Whether this verdict tells the UI that an update is available.
    pub fn update_available(self) -> bool {
        matches!(self, Self::NewerVersion | Self::Rebuild)
    }
}

/// Result of comparing a remote release against the local build.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UpdateDecision {
    pub update_available: bool,
    pub reason: UpdateReason,
}

/// Strips one leading `v`/`V` from a tag, ignoring surrounding whitespace.
pub fn strip_v_prefix(tag: &str) -> &str {
    let trimmed = tag.trim();
    trimmed
        .strip_prefix('v')
        .or_else(|| trimmed.strip_prefix('V'))
        .unwrap_or(trimmed)
}

/// Parses a GitHub tag (`v1.0.0-alpha.6`, `1.0.0`, ...) as semver.
///
/// Invalid tags map to [`ErrorCode::InvalidVersion`]; release selection skips
/// them instead of aborting the whole list.
pub fn parse_tag(tag: &str) -> Result<Version, AppError> {
    Version::parse(strip_v_prefix(tag)).map_err(|error| {
        AppError::new(
            ErrorCode::InvalidVersion,
            format!("无法解析版本号 {tag:?}：{error}"),
        )
    })
}

/// Compares two tags with semver precedence (`alpha.9 < alpha.10`).
#[allow(dead_code)] // Public comparison helper exercised by tests; `check` uses evaluate_update.
pub fn compare_tags(left: &str, right: &str) -> Result<Ordering, AppError> {
    Ok(parse_tag(left)?.cmp(&parse_tag(right)?))
}

/// Applies the plan's four-state update rule.
///
/// `remote > local` -> `newer_version`; equal versions with a later remote
/// build date -> `rebuild`; `remote < local` -> `local_newer`; everything else
/// (including a missing/invalid local date) -> `none`.
pub fn evaluate_update(
    local_version: &str,
    local_date: Option<&str>,
    remote_version: &str,
    remote_date: Option<&str>,
) -> Result<UpdateDecision, AppError> {
    let local = parse_tag(local_version)?;
    let remote = parse_tag(remote_version)?;

    let reason = match remote.cmp(&local) {
        Ordering::Greater => UpdateReason::NewerVersion,
        Ordering::Less => UpdateReason::LocalNewer,
        Ordering::Equal => match (parse_date(local_date), parse_date(remote_date)) {
            (Some(local), Some(remote)) if remote > local => UpdateReason::Rebuild,
            _ => UpdateReason::None,
        },
    };

    Ok(UpdateDecision {
        update_available: reason.update_available(),
        reason,
    })
}

/// Parses a strict `YYYY-MM-DD` date; anything else is not comparable.
fn parse_date(value: Option<&str>) -> Option<NaiveDate> {
    NaiveDate::parse_from_str(value?.trim(), "%Y-%m-%d").ok()
}

#[cfg(test)]
mod tests {
    use std::cmp::Ordering;

    use super::*;
    use crate::error::ErrorCode;

    #[test]
    fn version_comparison_covers_twelve_cases() {
        let cases = [
            ("v1.0.0-alpha.9", "v1.0.0-alpha.10", Ordering::Less),
            ("1.0.0-alpha.5", "v1.0.0-alpha.6", Ordering::Less),
            ("v1.0.0-alpha.6", "v1.0.0-beta.1", Ordering::Less),
            ("v1.0.0-beta.1", "v1.0.0", Ordering::Less),
            ("v1.0.0", "v1.0.0", Ordering::Equal),
            ("v1.0.0-alpha.10", "v1.0.0-alpha.9", Ordering::Greater),
            ("v2.0.0", "v1.9.9", Ordering::Greater),
            ("v1.0.0-alpha.1", "v1.0.0-alpha.1", Ordering::Equal),
            ("v1.0.1", "v1.0.0", Ordering::Greater),
            ("v1.1.0", "v1.0.9", Ordering::Greater),
            ("v1.0.0-alpha.2", "v1.0.0-alpha.10", Ordering::Less),
            ("v1.0.0-rc.1", "v1.0.0", Ordering::Less),
        ];
        assert_eq!(cases.len(), 12, "the plan requires twelve comparison cases");
        for (left, right, expected) in cases {
            assert_eq!(
                compare_tags(left, right).expect("compare"),
                expected,
                "{left} vs {right}"
            );
        }
    }

    #[test]
    fn version_strips_v_prefix_and_rejects_invalid_tags() {
        assert_eq!(strip_v_prefix("v1.0.0-alpha.5"), "1.0.0-alpha.5");
        assert_eq!(strip_v_prefix("V1.0.0"), "1.0.0");
        assert_eq!(strip_v_prefix("1.0.0"), "1.0.0");
        assert_eq!(
            parse_tag("v1.0.0-alpha.5").expect("parse").to_string(),
            "1.0.0-alpha.5"
        );

        let error = parse_tag("not-a-version").expect_err("invalid tag must fail");
        assert_eq!(error.code, ErrorCode::InvalidVersion);
        let error = compare_tags("v1.0.0", "not-a-version").expect_err("invalid tag must fail");
        assert_eq!(error.code, ErrorCode::InvalidVersion);
    }

    #[test]
    fn version_update_decisions_cover_four_states() {
        let newer = evaluate_update(
            "1.0.0-alpha.5",
            Some("2026-05-22"),
            "1.0.0-alpha.6",
            Some("2026-06-01"),
        )
        .expect("decision");
        assert_eq!(newer.reason, UpdateReason::NewerVersion);
        assert!(newer.update_available);

        let rebuild = evaluate_update(
            "1.0.0-alpha.5",
            Some("2026-05-22"),
            "1.0.0-alpha.5",
            Some("2026-05-23"),
        )
        .expect("decision");
        assert_eq!(rebuild.reason, UpdateReason::Rebuild);
        assert!(rebuild.update_available);

        let none = evaluate_update(
            "1.0.0-alpha.5",
            Some("2026-05-22"),
            "1.0.0-alpha.5",
            Some("2026-05-22"),
        )
        .expect("decision");
        assert_eq!(none.reason, UpdateReason::None);
        assert!(!none.update_available);

        let local_newer = evaluate_update(
            "1.0.0-alpha.6",
            Some("2026-06-01"),
            "1.0.0-alpha.5",
            Some("2026-05-22"),
        )
        .expect("decision");
        assert_eq!(local_newer.reason, UpdateReason::LocalNewer);
        assert!(!local_newer.update_available);
    }

    #[test]
    fn version_missing_local_date_disables_rebuild() {
        let decision = evaluate_update("1.0.0-alpha.5", None, "1.0.0-alpha.5", Some("2026-05-23"))
            .expect("decision");
        assert_eq!(decision.reason, UpdateReason::None);
        assert!(!decision.update_available);
    }

    #[test]
    fn version_reason_names_match_the_contract() {
        assert_eq!(UpdateReason::NewerVersion.as_str(), "newer_version");
        assert_eq!(UpdateReason::Rebuild.as_str(), "rebuild");
        assert_eq!(UpdateReason::LocalNewer.as_str(), "local_newer");
        assert_eq!(UpdateReason::None.as_str(), "none");
        assert!(UpdateReason::NewerVersion.update_available());
        assert!(UpdateReason::Rebuild.update_available());
        assert!(!UpdateReason::LocalNewer.update_available());
        assert!(!UpdateReason::None.update_available());
    }
}
