//! Resume state for `download`: `<dest>.part` plus its `<dest>.part.json` sidecar.
//!
//! The metadata is written atomically (`.tmp` + `std::fs::rename`) so a crash
//! can never leave a half-written JSON file that would make the next resume
//! decision wrong. `NotFound` is always treated as "no state", never as an
//! error: the cancel path may delete the sidecar while a download thread
//! is still finishing.

use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::error::{AppError, ErrorCode};

/// Schema revision of the sidecar JSON. Bump when fields change incompatibly.
pub const PART_SCHEMA: u32 = 1;

/// `<dest>.part.json` payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PartMeta {
    pub schema: u32,
    pub source_url: String,
    pub etag: Option<String>,
    pub total: u64,
    pub sha256: String,
    pub expected_size: u64,
}

impl PartMeta {
    /// Builds a schema-1 sidecar for the given request.
    pub fn new(
        source_url: impl Into<String>,
        etag: Option<String>,
        total: u64,
        sha256: impl Into<String>,
        expected_size: u64,
    ) -> Self {
        Self {
            schema: PART_SCHEMA,
            source_url: source_url.into(),
            etag,
            total,
            sha256: sha256.into(),
            expected_size,
        }
    }

    /// Whether a pre-existing part may be resumed for this request.
    ///
    /// All identity fields must match and the part must not be longer than the
    /// server-reported total.
    pub fn is_resumable(
        &self,
        source_url: &str,
        sha256: &str,
        expected_size: u64,
        part_len: u64,
    ) -> bool {
        self.schema == PART_SCHEMA
            && self.source_url == source_url
            && self.sha256 == sha256
            && self.expected_size == expected_size
            && part_len <= self.total
    }
}

/// `<dest>.part` beside the final installer.
pub fn part_path(dest: &Path) -> PathBuf {
    append_suffix(dest, ".part")
}

/// `<dest>.part.json` beside the final installer.
pub fn meta_path(dest: &Path) -> PathBuf {
    append_suffix(dest, ".part.json")
}

fn append_suffix(path: &Path, suffix: &str) -> PathBuf {
    let mut value = path.as_os_str().to_os_string();
    value.push(suffix);
    PathBuf::from(value)
}

/// Loads a sidecar. Missing or malformed files yield `None` (start over).
pub fn load_meta(path: &Path) -> Result<Option<PartMeta>, AppError> {
    let text = match fs::read_to_string(path) {
        Ok(text) => text,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => {
            return Err(AppError::new(
                ErrorCode::Io,
                format!("读取续传元数据失败：{error}"),
            ))
        }
    };
    let meta = match serde_json::from_str::<PartMeta>(&text) {
        Ok(meta) => meta,
        Err(_) => return Ok(None),
    };
    if meta.schema != PART_SCHEMA {
        return Ok(None);
    }
    Ok(Some(meta))
}

/// Atomically replaces the sidecar (`.tmp` + `std::fs::rename`).
pub fn write_meta(path: &Path, meta: &PartMeta) -> Result<(), AppError> {
    let tmp = append_suffix(path, ".tmp");
    let encoded = serde_json::to_vec(meta).map_err(|error| {
        AppError::new(ErrorCode::Internal, format!("序列化元数据失败：{error}"))
    })?;
    if let Err(error) = fs::write(&tmp, encoded) {
        let _ = fs::remove_file(&tmp);
        return Err(AppError::new(
            ErrorCode::Io,
            format!("写入续传元数据失败：{error}"),
        ));
    }
    if let Err(error) = fs::rename(&tmp, path) {
        let _ = fs::remove_file(&tmp);
        return Err(AppError::new(
            ErrorCode::Io,
            format!("提交续传元数据失败：{error}"),
        ));
    }
    Ok(())
}

/// Removes a file, treating `NotFound` as success (idempotent cleanup).
pub fn remove_file_if_exists(path: &Path) -> Result<(), AppError> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(AppError::new(
            ErrorCode::Io,
            format!("删除文件失败 {}：{error}", path.display()),
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn state_paths_append_suffixes_next_to_destination() {
        let dest = Path::new("C:\\downloads\\FreeAssetFilter_Setup.exe");
        assert_eq!(
            part_path(dest),
            PathBuf::from("C:\\downloads\\FreeAssetFilter_Setup.exe.part")
        );
        assert_eq!(
            meta_path(dest),
            PathBuf::from("C:\\downloads\\FreeAssetFilter_Setup.exe.part.json")
        );
    }

    #[test]
    fn state_meta_write_is_atomic_and_replaces_previous_value() {
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("a.exe.part.json");

        let first = PartMeta::new(
            "https://github.com/a.exe",
            None,
            1 << 20,
            "a".repeat(64),
            1 << 20,
        );
        write_meta(&path, &first).expect("write first");
        assert_eq!(load_meta(&path).expect("load").as_ref(), Some(&first));

        let second = PartMeta::new(
            "https://github.com/a.exe",
            Some("\"etag-2\"".to_owned()),
            1 << 20,
            "a".repeat(64),
            1 << 20,
        );
        write_meta(&path, &second).expect("write second");
        assert_eq!(load_meta(&path).expect("load").as_ref(), Some(&second));
        assert!(
            !dir.path().join("a.exe.part.json.tmp").exists(),
            "temporary sidecar must be renamed away"
        );
    }

    #[test]
    fn state_corrupt_or_missing_meta_means_start_over() {
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("a.exe.part.json");
        assert_eq!(load_meta(&path).expect("missing is fine"), None);

        fs::write(&path, b"{not json").expect("write corrupt");
        assert_eq!(load_meta(&path).expect("corrupt is fine"), None);

        let wrong_schema = PartMeta {
            schema: 99,
            ..PartMeta::new("https://github.com/a.exe", None, 10, "a".repeat(64), 10)
        };
        fs::write(&path, serde_json::to_vec(&wrong_schema).expect("serialize"))
            .expect("write schema");
        assert_eq!(load_meta(&path).expect("wrong schema is fine"), None);
    }

    #[test]
    fn state_resume_requires_identity_match_and_short_enough_part() {
        let meta = PartMeta::new("https://github.com/a.exe", None, 100, "a".repeat(64), 100);
        assert!(meta.is_resumable("https://github.com/a.exe", &"a".repeat(64), 100, 99));
        assert!(meta.is_resumable("https://github.com/a.exe", &"a".repeat(64), 100, 100));
        assert!(!meta.is_resumable("https://github.com/a.exe", &"b".repeat(64), 100, 50));
        assert!(!meta.is_resumable("https://github.com/b.exe", &"a".repeat(64), 100, 50));
        assert!(!meta.is_resumable("https://github.com/a.exe", &"a".repeat(64), 101, 50));
        assert!(!meta.is_resumable("https://github.com/a.exe", &"a".repeat(64), 100, 101));
    }

    #[test]
    fn state_remove_is_idempotent() {
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("missing.bin");
        remove_file_if_exists(&path).expect("missing is fine");
        fs::write(&path, b"x").expect("write");
        remove_file_if_exists(&path).expect("remove");
        assert!(!path.exists());
    }
}
