//! Version parsing, ordering and update decisions (plan C2).
//!
//! Pure functions only: no I/O and no network. The `check` command
//! consumes these to compare the local `SPKVERSION` against a GitHub tag.
//!
//! Three shapes have to stay comparable:
//!
//! * plain semver (`1.0.0`, `1.0.0-alpha.6`, `2.0.0-rc.1`);
//! * the nightly snapshot the release pipeline writes into `SPKVERSION`
//!   (`2.0.0.nightly-20261114`) — four dot-separated parts, which strict
//!   semver rejects;
//! * a nightly snapshot must outrank the plain release with the same core,
//!   because it is built from the code that comes *after* that release. This
//!   mirrors the installer's own four-part version, whose 4th field is the
//!   build date (`2.0.0` -> `2.0.0.20261114`).

use std::cmp::Ordering;
use std::fmt;
use std::sync::OnceLock;

use chrono::NaiveDate;
use regex::Regex;
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

/// Where a version sits relative to the plain release of the same core.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Stage {
    /// Semver pre-release (`alpha.5`, `beta.1`, `rc.2`); ranked below the release.
    Pre(Version),
    /// The plain release itself (`1.0.0`).
    Release,
    /// Nightly snapshot built after the release (`2.0.0.nightly-20261114`).
    Nightly(NaiveDate),
}

/// Comparable, scheme-aware version key.
///
/// Ordering is `major`, `minor`, `patch`, then [`Stage`]; so
/// `1.0.0-alpha.9 < 1.0.0 < 2.0.0.nightly-20261114` holds.
///
/// Equality follows [`Ord`] (not the stored shape) so that, for example,
/// semver build metadata never makes two equal-precedence versions unequal.
#[derive(Debug, Clone)]
pub struct VersionKey {
    pub major: u64,
    pub minor: u64,
    pub patch: u64,
    pub stage: Stage,
}

impl VersionKey {
    /// Canonical text form, matching what `SPKVERSION` and tags carry.
    pub fn display(&self) -> String {
        self.to_string()
    }
}

impl fmt::Display for VersionKey {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match &self.stage {
            Stage::Pre(version) => write!(formatter, "{version}"),
            Stage::Release => write!(formatter, "{}.{}.{}", self.major, self.minor, self.patch),
            Stage::Nightly(date) => write!(
                formatter,
                "{}.{}.{}.nightly-{}",
                self.major,
                self.minor,
                self.patch,
                date.format("%Y%m%d")
            ),
        }
    }
}

impl PartialEq for VersionKey {
    fn eq(&self, other: &Self) -> bool {
        self.cmp(other) == Ordering::Equal
    }
}

impl Eq for VersionKey {}

impl PartialOrd for VersionKey {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for VersionKey {
    fn cmp(&self, other: &Self) -> Ordering {
        self.major
            .cmp(&other.major)
            .then_with(|| self.minor.cmp(&other.minor))
            .then_with(|| self.patch.cmp(&other.patch))
            .then_with(|| match (&self.stage, &other.stage) {
                (Stage::Pre(left), Stage::Pre(right)) => left.cmp(right),
                (Stage::Pre(_), _) => Ordering::Less,
                (_, Stage::Pre(_)) => Ordering::Greater,
                (Stage::Release, Stage::Release) => Ordering::Equal,
                (Stage::Release, Stage::Nightly(_)) => Ordering::Less,
                (Stage::Nightly(_), Stage::Release) => Ordering::Greater,
                (Stage::Nightly(left), Stage::Nightly(right)) => left.cmp(right),
            })
    }
}

/// `<major>.<minor>.<patch>.nightly-<YYYYMMDD>` (also accepts a `.nightly.` separator).
fn nightly_regex() -> &'static Regex {
    static REGEX: OnceLock<Regex> = OnceLock::new();
    REGEX.get_or_init(|| {
        Regex::new(r"^(\d+)\.(\d+)\.(\d+)\.nightly[-.](\d{8})$")
            .expect("nightly version regex must compile")
    })
}

/// Parses a GitHub tag or a local `SPKVERSION` line.
///
/// Accepts semver (`v1.0.0-alpha.6`, `2.0.0`) and the nightly snapshot shape
/// (`2.0.0.nightly-20261114`). Anything else maps to
/// [`ErrorCode::InvalidVersion`]; release selection skips such tags instead of
/// aborting the whole list.
pub fn parse_version(raw: &str) -> Result<VersionKey, AppError> {
    let value = strip_v_prefix(raw);
    match Version::parse(value) {
        Ok(version) => Ok(from_semver(version)),
        Err(error) => {
            if let Some(key) = parse_nightly(value) {
                return Ok(key);
            }
            Err(AppError::new(
                ErrorCode::InvalidVersion,
                format!("无法解析版本号 {raw:?}：{error}"),
            ))
        }
    }
}

/// Builds a key from an already-parsed semver value.
fn from_semver(version: Version) -> VersionKey {
    let stage = if version.pre.is_empty() {
        Stage::Release
    } else {
        Stage::Pre(version.clone())
    };
    VersionKey {
        major: version.major,
        minor: version.minor,
        patch: version.patch,
        stage,
    }
}

/// Matches the pipeline's nightly snapshot shape; `None` when it does not match.
fn parse_nightly(value: &str) -> Option<VersionKey> {
    let captures = nightly_regex().captures(value)?;
    let date = NaiveDate::parse_from_str(captures.get(4)?.as_str(), "%Y%m%d").ok()?;
    Some(VersionKey {
        major: captures.get(1)?.as_str().parse().ok()?,
        minor: captures.get(2)?.as_str().parse().ok()?,
        patch: captures.get(3)?.as_str().parse().ok()?,
        stage: Stage::Nightly(date),
    })
}

/// Compares two tags with semver precedence (`alpha.9 < alpha.10`).
#[allow(dead_code)] // Public comparison helper exercised by tests; `check` uses evaluate_update.
pub fn compare_tags(left: &str, right: &str) -> Result<Ordering, AppError> {
    Ok(parse_version(left)?.cmp(&parse_version(right)?))
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
    let local = parse_version(local_version)?;
    let remote = parse_version(remote_version)?;

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
            parse_version("v1.0.0-alpha.5").expect("parse").to_string(),
            "1.0.0-alpha.5"
        );

        let error = parse_version("not-a-version").expect_err("invalid tag must fail");
        assert_eq!(error.code, ErrorCode::InvalidVersion);
        let error = compare_tags("v1.0.0", "not-a-version").expect_err("invalid tag must fail");
        assert_eq!(error.code, ErrorCode::InvalidVersion);
    }

    #[test]
    fn version_nightly_snapshots_parse_and_display_unchanged() {
        for (raw, expected) in [
            ("2.0.0.nightly-20261114", "2.0.0.nightly-20261114"),
            ("v2.0.0.nightly-20261114", "2.0.0.nightly-20261114"),
            ("2.0.0.nightly.20261114", "2.0.0.nightly-20261114"),
        ] {
            let parsed = parse_version(raw).unwrap_or_else(|error| panic!("{raw}: {error}"));
            assert_eq!(parsed.display(), expected);
            assert_eq!(parsed.major, 2);
            assert_eq!(parsed.minor, 0);
            assert_eq!(parsed.patch, 0);
            assert!(matches!(parsed.stage, Stage::Nightly(_)));
        }
    }

    #[test]
    fn version_nightly_ranks_above_its_base_release_and_by_date() {
        let nightly = parse_version("2.0.0.nightly-20261114").expect("nightly");
        let release = parse_version("v2.0.0").expect("release");
        let later = parse_version("2.0.0.nightly-20261115").expect("later nightly");
        let alpha = parse_version("2.0.0-alpha.5").expect("alpha");

        assert!(nightly > release, "nightly is built after the release");
        assert!(later > nightly);
        assert!(nightly > alpha);
        assert_eq!(
            nightly,
            parse_version("2.0.0.nightly-20261114").expect("same")
        );

        // The core version still dominates the stage.
        let next_core_alpha = parse_version("2.1.0-alpha.1").expect("next core");
        let far_nightly = parse_version("2.0.0.nightly-20261231").expect("far nightly");
        assert!(next_core_alpha > far_nightly);
    }

    #[test]
    fn version_nightly_snapshot_rejects_broken_shapes() {
        for raw in [
            "2.0.0.nightly-2026111",
            "2.0.0.nightly-20261332",
            "2.0.0.nightly",
            "nightly",
            "2.0.nightly-20261114",
        ] {
            let error = parse_version(raw).expect_err("must fail");
            assert_eq!(error.code, ErrorCode::InvalidVersion, "{raw}");
        }
        let error = parse_version("2.0.0.nightly-2026111").expect_err("short date");
        assert!(
            error.message.contains("2.0.0.nightly-2026111"),
            "the message must name the offending version, got {:?}",
            error.message
        );
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
    fn version_update_decisions_accept_nightly_on_both_sides() {
        // nightlies of the same core: only a later date is an update
        let newer = evaluate_update(
            "2.0.0.nightly-20261114",
            Some("2026-11-14"),
            "2.0.0.nightly-20261115",
            Some("2026-11-15"),
        )
        .expect("decision");
        assert_eq!(newer.reason, UpdateReason::NewerVersion);
        assert!(newer.update_available);

        let same = evaluate_update(
            "2.0.0.nightly-20261114",
            Some("2026-11-14"),
            "2.0.0.nightly-20261114",
            Some("2026-11-14"),
        )
        .expect("decision");
        assert_eq!(same.reason, UpdateReason::None);

        let rebuilt = evaluate_update(
            "2.0.0.nightly-20261114",
            Some("2026-11-14"),
            "2.0.0.nightly-20261114",
            Some("2026-11-15"),
        )
        .expect("decision");
        assert_eq!(rebuilt.reason, UpdateReason::Rebuild);

        // a nightly user is never told to "update" to the older plain release
        let local_nightly = evaluate_update(
            "2.0.0.nightly-20261114",
            Some("2026-11-14"),
            "v2.0.0",
            Some("2026-11-13"),
        )
        .expect("decision");
        assert_eq!(local_nightly.reason, UpdateReason::LocalNewer);
        assert!(!local_nightly.update_available);

        // a release user asking for prereleases does get the nightly
        let local_release = evaluate_update(
            "2.0.0",
            Some("2026-11-13"),
            "2.0.0.nightly-20261114",
            Some("2026-11-14"),
        )
        .expect("decision");
        assert_eq!(local_release.reason, UpdateReason::NewerVersion);
        assert!(local_release.update_available);
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
