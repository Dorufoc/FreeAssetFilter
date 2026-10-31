//! Cross-cutting scaffold assertions that do not belong to a single module.

use std::fs;
use std::path::PathBuf;

fn crate_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

/// Drops the `#[cfg(test)]` tail so assertion literals are not mistaken for
/// production code.
fn production_part(source: &'static str) -> &'static str {
    source.split("#[cfg(test)]").next().unwrap_or(source)
}

#[test]
fn production_sources_never_reference_the_forbidden_read_timeout() {
    let sources = [
        ("main.rs", include_str!("main.rs")),
        ("error.rs", include_str!("error.rs")),
        ("protocol.rs", include_str!("protocol.rs")),
        ("http.rs", include_str!("http.rs")),
        ("watchdog.rs", include_str!("watchdog.rs")),
    ];
    for (name, source) in sources {
        let forbidden = ["timeout_", "per_", "read"].concat();
        assert!(
            !production_part(source).contains(&forbidden),
            "{name} must rely on the progress watchdog instead of a read timeout"
        );
    }
}

#[test]
fn cargo_manifest_matches_the_plan_dependency_set() {
    let manifest = include_str!("../Cargo.toml");
    assert!(manifest.contains("edition = \"2021\""));
    assert!(manifest.contains("name = \"spk_updater\""));
    assert!(manifest.contains(
        "ureq = { version = \"3\", default-features = false, features = [\"native-tls\"] }"
    ));
    assert!(manifest.contains("url = \"2\""));
    assert!(manifest.contains("regex = \"1\""));
    assert!(manifest.contains("sha2 = \"0.10\""));
    assert!(manifest.contains("semver = \"1\""));
    assert!(manifest.contains(
        "chrono = { version = \"0.4\", default-features = false, features = [\"std\"] }"
    ));
    assert!(manifest.contains("windows-sys"));
    assert!(
        !manifest.contains("features = [\"gzip\"]"),
        "compressed transfer encoding must stay disabled"
    );
    assert!(manifest.contains("tiny_http"));
    assert!(manifest.contains("tempfile"));
}

#[test]
fn scaffold_sources_are_present() {
    for relative in [
        "Cargo.toml",
        "build_updater.py",
        "src/main.rs",
        "src/protocol.rs",
        "src/error.rs",
        "src/http.rs",
        "src/watchdog.rs",
    ] {
        let path = crate_dir().join(relative);
        assert!(path.is_file(), "missing scaffold file: {relative}");
        assert!(
            fs::metadata(&path).expect("metadata").len() > 0,
            "empty scaffold file: {relative}"
        );
    }
}
