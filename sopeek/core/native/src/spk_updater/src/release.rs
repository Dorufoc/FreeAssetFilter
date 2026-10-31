//! GitHub release-list parsing, installer selection and release metadata (plan C2).
//!
//! Pure functions only: no HTTP and no file downloads. The `check` command
//! feeds the GitHub JSON in and serializes the selected release out.

use std::sync::OnceLock;

use chrono::NaiveDate;
use regex::Regex;
use semver::Version;
use serde::{Deserialize, Serialize};

use crate::error::{AppError, ErrorCode};
use crate::version::parse_tag;

/// Maximum number of characters kept from a release body.
pub const MAX_NOTES_CHARS: usize = 20_000;
/// Only release pages under this exact prefix may reach `QDesktopServices`.
pub const RELEASE_HTML_PREFIX: &str = "https://github.com/Dorufoc/Sopeek/releases/";

const WIN10_WIN11_X64_SETUP_SCORE: u32 = 100;
const SETUP_SCORE: u32 = 50;

/// One entry of the GitHub `GET /releases` list.
///
/// Unknown fields are ignored on purpose: GitHub adds fields over time and a
/// new key must never break update checking.
#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize)]
pub struct Release {
    pub tag_name: Option<String>,
    pub name: Option<String>,
    pub body: Option<String>,
    pub draft: Option<bool>,
    pub prerelease: Option<bool>,
    pub published_at: Option<String>,
    pub created_at: Option<String>,
    pub html_url: Option<String>,
    #[serde(default)]
    pub assets: Vec<Asset>,
}

/// One release asset.
#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize)]
pub struct Asset {
    pub name: Option<String>,
    pub size: Option<u64>,
    pub digest: Option<String>,
    pub browser_download_url: Option<String>,
}

/// `check.result.remote` payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RemoteRelease {
    pub version: String,
    pub tag: String,
    pub date: Option<String>,
    pub published_at: Option<String>,
    pub prerelease: bool,
    pub html_url: Option<String>,
    pub notes: String,
    pub notes_truncated: bool,
}

/// `check.result.asset` payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InstallerAsset {
    pub name: String,
    pub size: u64,
    pub sha256: Option<String>,
    pub download_url: String,
}

/// Fully resolved release + installer pair.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SelectedRelease {
    pub remote: RemoteRelease,
    pub asset: InstallerAsset,
    pub skipped_newer_tag: Option<String>,
}

/// Parses a GitHub release-list response body.
pub fn parse_releases(json: &str) -> Result<Vec<Release>, AppError> {
    serde_json::from_str(json).map_err(|error| {
        AppError::new(
            ErrorCode::InvalidJson,
            format!("无法解析 GitHub releases JSON：{error}"),
        )
    })
}

/// Parses the list and selects the newest release that has a usable installer.
pub fn resolve_releases(json: &str, include_prerelease: bool) -> Result<SelectedRelease, AppError> {
    let releases = parse_releases(json)?;
    select_release(&releases, include_prerelease)
}

/// Scores an installer candidate, or returns `None` when it is not eligible.
///
/// A candidate must end in `.exe` (case-insensitive) and its basename must
/// contain `setup` (case-insensitive). `win10_win11_x64_setup` outranks a plain
/// `setup`; portable/launcher executables never qualify.
fn setup_exe_score(name: &str) -> Option<u32> {
    let lower = name.to_ascii_lowercase();
    if !lower.ends_with(".exe") || !lower.contains("setup") {
        return None;
    }
    if lower.contains("win10_win11_x64_setup") {
        Some(WIN10_WIN11_X64_SETUP_SCORE)
    } else {
        Some(SETUP_SCORE)
    }
}

/// Picks the best installer asset in a release.
///
/// Highest score wins; ties go to the larger `size`.
pub fn select_installer_asset(assets: &[Asset]) -> Option<&Asset> {
    assets
        .iter()
        .filter_map(|asset| {
            let name = asset.name.as_deref()?;
            let url = asset.browser_download_url.as_deref()?;
            if url.is_empty() {
                return None;
            }
            let score = setup_exe_score(name)?;
            Some((score, asset.size.unwrap_or(0), asset))
        })
        .max_by(|left, right| left.0.cmp(&right.0).then(left.1.cmp(&right.1)))
        .map(|(_, _, asset)| asset)
}

/// Selects the release to advertise to the UI (plan C2).
///
/// Drafts are always filtered; prereleases are filtered unless
/// `include_prerelease` is set. Invalid tags are skipped. Among releases that
/// contain a usable setup `.exe`, the highest semver wins (same version ->
/// later `published_at`). When the newest eligible tag has no installer, the
/// next usable release is chosen and the skipped tag is reported.
pub fn select_release(
    releases: &[Release],
    include_prerelease: bool,
) -> Result<SelectedRelease, AppError> {
    let eligible: Vec<&Release> = releases
        .iter()
        .filter(|release| {
            !release.draft.unwrap_or(false)
                && (include_prerelease || !release.prerelease.unwrap_or(false))
        })
        .collect();
    if eligible.is_empty() {
        return Err(no_release());
    }

    let parsed: Vec<(&Release, Version)> = eligible
        .iter()
        .filter_map(|release| {
            let tag = release.tag_name.as_deref()?.trim();
            if tag.is_empty() {
                return None;
            }
            parse_tag(tag).ok().map(|version| (*release, version))
        })
        .collect();
    if parsed.is_empty() {
        return Err(no_release());
    }

    let chosen = parsed
        .iter()
        .filter_map(|(release, version)| {
            let asset = select_installer_asset(&release.assets)?;
            Some((*release, version, asset))
        })
        .max_by(|left, right| {
            left.1
                .cmp(right.1)
                .then_with(|| published_key(left.0).cmp(published_key(right.0)))
        });
    let Some((chosen_release, chosen_version, chosen_asset)) = chosen else {
        return Err(no_installer_asset());
    };

    let newest = parsed
        .iter()
        .max_by(|left, right| {
            left.1
                .cmp(&right.1)
                .then_with(|| published_key(left.0).cmp(published_key(right.0)))
        })
        .expect("parsed is non-empty");

    let skipped_newer_tag = if std::ptr::eq(newest.0, chosen_release) {
        None
    } else {
        newest.0.tag_name.clone()
    };

    let (notes, notes_truncated) = normalize_notes(chosen_release.body.as_deref());
    let remote = RemoteRelease {
        version: chosen_version.to_string(),
        tag: chosen_release.tag_name.clone().unwrap_or_default(),
        date: extract_build_date(
            chosen_release.body.as_deref(),
            chosen_release.published_at.as_deref(),
        ),
        published_at: chosen_release.published_at.clone(),
        prerelease: chosen_release.prerelease.unwrap_or(false),
        html_url: sanitize_html_url(chosen_release.html_url.as_deref()),
        notes,
        notes_truncated,
    };
    let asset = InstallerAsset {
        name: chosen_asset.name.clone().unwrap_or_default(),
        size: chosen_asset.size.unwrap_or(0),
        sha256: parse_digest(chosen_asset.digest.as_deref()),
        download_url: chosen_asset
            .browser_download_url
            .clone()
            .unwrap_or_default(),
    };

    Ok(SelectedRelease {
        remote,
        asset,
        skipped_newer_tag,
    })
}

/// Lexicographic key for ISO-8601 UTC timestamps (missing sorts first).
fn published_key(release: &Release) -> &str {
    release.published_at.as_deref().unwrap_or("")
}

/// Extracts `构建日期` from the body, falling back to `published_at`'s date.
pub fn extract_build_date(body: Option<&str>, published_at: Option<&str>) -> Option<String> {
    body.and_then(body_build_date)
        .or_else(|| published_at_date(published_at))
}

fn body_build_date(body: &str) -> Option<String> {
    let captures = build_date_regex().captures(body)?;
    let year = captures.get(1)?.as_str().parse::<i32>().ok()?;
    let month = captures.get(2)?.as_str().parse::<u32>().ok()?;
    let day = captures.get(3)?.as_str().parse::<u32>().ok()?;
    let date = NaiveDate::from_ymd_opt(year, month, day)?;
    Some(date.format("%Y-%m-%d").to_string())
}

fn published_at_date(published_at: Option<&str>) -> Option<String> {
    let text = published_at?.trim();
    let prefix = text.get(..10)?;
    let date = NaiveDate::parse_from_str(prefix, "%Y-%m-%d").ok()?;
    Some(date.format("%Y-%m-%d").to_string())
}

/// `构建日期：YYYY/MM/DD` with ASCII or full-width colon and `/` or `-`.
fn build_date_regex() -> &'static Regex {
    static REGEX: OnceLock<Regex> = OnceLock::new();
    REGEX.get_or_init(|| {
        Regex::new(r"构建日期\s*[：:]\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})")
            .expect("build-date regex must compile")
    })
}

/// Trims release notes and truncates to [`MAX_NOTES_CHARS`] characters.
///
/// Truncation walks `char`s, so multi-byte UTF-8 characters are never split.
pub fn normalize_notes(body: Option<&str>) -> (String, bool) {
    let trimmed = body.unwrap_or("").trim();
    let mut notes = String::with_capacity(trimmed.len().min(MAX_NOTES_CHARS * 3));
    let mut truncated = false;
    for (index, character) in trimmed.chars().enumerate() {
        if index == MAX_NOTES_CHARS {
            truncated = true;
            break;
        }
        notes.push(character);
    }
    (notes, truncated)
}

/// Keeps `html_url` only when it starts with the exact release-page prefix.
pub fn sanitize_html_url(url: Option<&str>) -> Option<String> {
    let url = url?;
    if url.starts_with(RELEASE_HTML_PREFIX) {
        Some(url.to_owned())
    } else {
        None
    }
}

/// Extracts a lowercase SHA-256 from `sha256:<hex>`, `SHA256:<hex>` or bare hex.
pub fn parse_digest(digest: Option<&str>) -> Option<String> {
    let value = digest?.trim();
    let hex = match value.split_once(':') {
        Some((algorithm, hex)) if algorithm.eq_ignore_ascii_case("sha256") => hex,
        Some(_) => return None,
        None => value,
    };
    let hex = hex.trim();
    if hex.len() == 64 && hex.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        Some(hex.to_ascii_lowercase())
    } else {
        None
    }
}

fn no_release() -> AppError {
    AppError::new(ErrorCode::NoRelease, "未找到可用的发布版本")
}

fn no_installer_asset() -> AppError {
    AppError::new(ErrorCode::NoInstallerAsset, "发布版本中没有可用的安装包")
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::PathBuf;

    use super::*;
    use crate::error::ErrorCode;

    fn fixture_path() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../../../../tests/fixtures/releases.json")
    }

    fn fixture_json() -> String {
        let path = fixture_path();
        assert!(
            path.is_file(),
            "missing release fixture at {}",
            path.display()
        );
        fs::read_to_string(&path).expect("read release fixture")
    }

    fn fixture_releases() -> Vec<Release> {
        parse_releases(&fixture_json()).expect("parse release fixture")
    }

    fn subset(releases: &[Release], tags: &[&str]) -> Vec<Release> {
        tags.iter()
            .map(|tag| {
                releases
                    .iter()
                    .find(|release| release.tag_name.as_deref() == Some(*tag))
                    .unwrap_or_else(|| panic!("fixture is missing tag {tag}"))
                    .clone()
            })
            .collect()
    }

    fn asset(name: &str, size: u64) -> Asset {
        Asset {
            name: Some(name.to_owned()),
            size: Some(size),
            digest: None,
            browser_download_url: Some(format!(
                "https://github.com/Dorufoc/Sopeek/{name}"
            )),
        }
    }

    #[test]
    fn release_fixture_parses_alpha_beta_stable_and_ignores_unknown_fields() {
        let releases = fixture_releases();
        assert_eq!(releases.len(), 8);

        let tags: Vec<&str> = releases
            .iter()
            .filter_map(|release| release.tag_name.as_deref())
            .collect();
        for expected in [
            "v1.0.0-alpha.6",
            "v1.0.0-alpha.9",
            "v1.0.0-alpha.10",
            "v1.0.0-beta.1",
            "v1.0.0",
            "not-a-version",
            "v1.0.0-alpha.7",
            "v1.0.0-alpha.8",
        ] {
            assert!(tags.contains(&expected), "missing fixture tag {expected}");
        }

        let alpha6 = releases
            .iter()
            .find(|release| release.tag_name.as_deref() == Some("v1.0.0-alpha.6"))
            .expect("alpha.6");
        assert_eq!(alpha6.assets.len(), 5);
        assert!(alpha6.body.as_deref().unwrap_or("").contains("中文路径"));
    }

    #[test]
    fn release_happy_path_selects_alpha6_setup_and_build_date() {
        let releases = fixture_releases();
        let selected = select_release(&subset(&releases, &["v1.0.0-alpha.6"]), true)
            .expect("alpha.6 is selectable");

        assert_eq!(selected.remote.version, "1.0.0-alpha.6");
        assert_eq!(selected.remote.tag, "v1.0.0-alpha.6");
        assert_eq!(selected.remote.date.as_deref(), Some("2026-06-01"));
        assert_eq!(
            selected.remote.published_at.as_deref(),
            Some("2026-06-02T01:02:03Z")
        );
        assert!(selected.remote.prerelease);
        assert!(selected.remote.notes.contains("中文路径"));
        assert!(!selected.remote.notes_truncated);
        assert_eq!(
            selected.remote.html_url.as_deref(),
            Some("https://github.com/Dorufoc/Sopeek/releases/tag/v1.0.0-alpha.6")
        );

        assert_eq!(
            selected.asset.name,
            "Sopeek-1.0.0-alpha.6_win10_win11_x64_Setup.exe"
        );
        assert_eq!(selected.asset.size, 172000000);
        assert_eq!(
            selected.asset.sha256.as_deref(),
            Some("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
        );
        assert!(selected
            .asset
            .download_url
            .starts_with("https://github.com/Dorufoc/Sopeek/releases/download/"));
        assert_eq!(selected.skipped_newer_tag, None);
    }

    #[test]
    fn release_build_date_supports_three_body_formats() {
        let releases = fixture_releases();
        for (tag, expected) in [
            ("v1.0.0-alpha.6", "2026-06-01"),
            ("v1.0.0-alpha.9", "2026-06-02"),
            ("v1.0.0-alpha.10", "2026-06-03"),
        ] {
            let selected =
                select_release(&subset(&releases, &[tag]), true).expect("release selectable");
            assert_eq!(
                selected.remote.date.as_deref(),
                Some(expected),
                "{tag} build date"
            );
        }
    }

    #[test]
    fn release_build_date_falls_back_to_published_at() {
        let releases = fixture_releases();
        let beta =
            select_release(&subset(&releases, &["v1.0.0-beta.1"]), true).expect("beta selectable");
        assert_eq!(beta.remote.date.as_deref(), Some("2026-06-10"));
        assert_eq!(beta.asset.sha256, None, "beta fixture has no digest");

        assert_eq!(
            extract_build_date(Some("构建日期：2026/13/40"), Some("2026-07-01T09:08:07Z"))
                .as_deref(),
            Some("2026-07-01"),
            "invalid body date must fall back to published_at"
        );
        assert_eq!(extract_build_date(None, None), None);
        assert_eq!(extract_build_date(Some("无日期"), None), None);
    }

    #[test]
    fn release_notes_truncate_at_20000_characters_on_utf8_boundaries() {
        assert_eq!(MAX_NOTES_CHARS, 20_000);

        let exact = "中".repeat(MAX_NOTES_CHARS);
        let (notes, truncated) = normalize_notes(Some(&exact));
        assert_eq!(notes, exact);
        assert!(!truncated);

        let over = format!("{}尾", "中".repeat(MAX_NOTES_CHARS));
        let (notes, truncated) = normalize_notes(Some(&over));
        assert_eq!(notes, "中".repeat(MAX_NOTES_CHARS));
        assert_eq!(notes.chars().count(), MAX_NOTES_CHARS);
        assert!(truncated);
        assert!(notes.is_char_boundary(notes.len()));

        let (notes, truncated) = normalize_notes(Some("  \n正文\n  "));
        assert_eq!(notes, "正文");
        assert!(!truncated);
    }

    #[test]
    fn release_asset_scoring_uses_five_candidate_shapes() {
        let candidates = vec![
            asset("Sopeek-1.0.0_win10_win11_x64_Setup.exe", 10),
            asset("Sopeek_Setup.exe", 1000),
            asset("Sopeek_Setup.EXE", 2000),
            asset("portable.exe", 64_000_000),
            asset("launcher.exe", 32_000_000),
        ];
        let selected = select_installer_asset(&candidates).expect("win10 setup wins");
        assert_eq!(
            selected.name.as_deref(),
            Some("Sopeek-1.0.0_win10_win11_x64_Setup.exe")
        );

        let without_top = &candidates[1..];
        let selected = select_installer_asset(without_top).expect("plain setup wins");
        assert_eq!(
            selected.name.as_deref(),
            Some("Sopeek_Setup.EXE"),
            "same score must prefer the larger size"
        );

        let excluded = &candidates[3..];
        assert!(
            select_installer_asset(excluded).is_none(),
            "portable.exe and launcher.exe must never be installer candidates"
        );

        assert!(select_installer_asset(&[asset("Sopeek_Setup.zip", 1)]).is_none());
    }

    #[test]
    fn release_digest_parsing_supports_three_formats() {
        let lower = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
        let upper = "FEDCBA9876543210FEDCBA9876543210FEDCBA9876543210FEDCBA9876543210";

        assert_eq!(
            parse_digest(Some(&format!("sha256:{lower}"))).as_deref(),
            Some(lower)
        );
        assert_eq!(
            parse_digest(Some(&format!("SHA256:{upper}"))).as_deref(),
            Some("fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210")
        );
        assert_eq!(parse_digest(Some(lower)).as_deref(), Some(lower));

        assert_eq!(parse_digest(Some(&format!("md5:{lower}"))), None);
        assert_eq!(parse_digest(Some("sha256:abc")), None);
        assert_eq!(parse_digest(None), None);
    }

    #[test]
    fn release_selection_falls_back_when_newest_tag_has_no_installer() {
        let releases = fixture_releases();
        let selected = select_release(
            &subset(&releases, &["v1.0.0-alpha.7", "v1.0.0-alpha.6"]),
            true,
        )
        .expect("older alpha.6 has an installer");

        assert_eq!(selected.remote.version, "1.0.0-alpha.6");
        assert_eq!(
            selected.skipped_newer_tag.as_deref(),
            Some("v1.0.0-alpha.7")
        );
    }

    #[test]
    fn release_selection_without_fallback_reports_null_skipped_tag() {
        let releases = fixture_releases();
        let selected = select_release(&subset(&releases, &["v1.0.0-alpha.6"]), true)
            .expect("alpha.6 selectable");
        assert_eq!(selected.skipped_newer_tag, None);
    }

    #[test]
    fn release_selection_without_any_installer_returns_no_installer_asset() {
        let releases = fixture_releases();
        let error = select_release(&subset(&releases, &["v1.0.0-alpha.7"]), true)
            .expect_err("alpha.7 has no setup exe");
        assert_eq!(error.code, ErrorCode::NoInstallerAsset);
    }

    #[test]
    fn release_selection_with_only_invalid_tags_returns_no_release() {
        let releases = fixture_releases();
        let error = select_release(&subset(&releases, &["not-a-version"]), true)
            .expect_err("invalid tag must be skipped");
        assert_eq!(error.code, ErrorCode::NoRelease);
    }

    #[test]
    fn release_selection_filters_drafts_and_prereleases() {
        let releases = fixture_releases();

        let error = select_release(&subset(&releases, &["v1.0.0-alpha.8"]), true)
            .expect_err("drafts are filtered");
        assert_eq!(error.code, ErrorCode::NoRelease);

        let error = select_release(&subset(&releases, &["v1.0.0-alpha.6"]), false)
            .expect_err("prereleases are filtered when include_prerelease=false");
        assert_eq!(error.code, ErrorCode::NoRelease);

        let stable = select_release(&releases, false).expect("stable release selectable");
        assert_eq!(stable.remote.version, "1.0.0");
        assert!(!stable.remote.prerelease);
    }

    #[test]
    fn release_selection_prefers_higher_semver_over_later_publish_time() {
        let releases = fixture_releases();
        let selected = select_release(
            &subset(&releases, &["v1.0.0-alpha.6", "v1.0.0-alpha.10"]),
            true,
        )
        .expect("alpha.10 is higher");
        assert_eq!(selected.remote.version, "1.0.0-alpha.10");
        assert_eq!(selected.skipped_newer_tag, None);
    }

    #[test]
    fn release_selection_breaks_same_version_ties_by_later_published_at() {
        let json = r#"[
            {"tag_name":"v1.0.0","draft":false,"prerelease":false,
             "published_at":"2026-06-01T00:00:00Z",
             "assets":[{"name":"Early_Setup.exe","size":10,
                        "browser_download_url":"https://github.com/Dorufoc/Sopeek/early.exe"}]},
            {"tag_name":"v1.0.0","draft":false,"prerelease":false,
             "published_at":"2026-06-02T00:00:00Z",
             "assets":[{"name":"Late_Setup.exe","size":20,
                        "browser_download_url":"https://github.com/Dorufoc/Sopeek/late.exe"}]}
        ]"#;
        let releases = parse_releases(json).expect("parse inline releases");
        let selected = select_release(&releases, true).expect("same version selectable");
        assert_eq!(selected.asset.name, "Late_Setup.exe");
        assert_eq!(selected.skipped_newer_tag, None);
    }

    #[test]
    fn release_html_url_only_keeps_the_exact_release_prefix() {
        let releases = fixture_releases();

        let valid = select_release(&subset(&releases, &["v1.0.0-alpha.6"]), true)
            .expect("alpha.6 selectable");
        assert!(valid.remote.html_url.is_some());

        let invalid =
            select_release(&subset(&releases, &["v1.0.0"]), true).expect("stable selectable");
        assert_eq!(
            invalid.remote.html_url, None,
            "foreign hosts must not reach QDesktopServices"
        );

        assert_eq!(sanitize_html_url(Some("file:///C:/x")), None);
        assert_eq!(
            sanitize_html_url(Some("https://github.com/Dorufoc/Sopeek/releases")),
            None
        );
        assert_eq!(
            sanitize_html_url(Some(
                "https://github.com/Dorufoc/Sopeek/releases/tag/v1.0.0"
            ))
            .as_deref(),
            Some("https://github.com/Dorufoc/Sopeek/releases/tag/v1.0.0")
        );
    }

    #[test]
    fn release_parse_rejects_invalid_json() {
        let error = parse_releases("{not json").expect_err("invalid JSON");
        assert_eq!(error.code, ErrorCode::InvalidJson);
    }
}
