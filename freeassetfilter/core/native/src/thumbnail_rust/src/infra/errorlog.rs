//! 环形错误日志缓冲（todo 5 实现）。
//!
//! 职责：Mutex 保护的环形错误缓冲，上限 512 条（溢出丢弃最旧），每条含
//! path/format/status/message/timestamp；供 T3 跳过路径与一切解码失败记录，
//! 并与 `lib.rs` 新导出 `native_get_error_log_json` / `native_clear_error_log`
//! 接线。JSON 序列化统一经 serde_json（Design Revision 5：不再自研 minijson）。
//!
//! # 线程安全
//! 全局缓冲 `ERROR_LOG` 由 `Mutex<ErrorBuffer>` 保护；`push_error` /
//! `clear_error_log` / `error_log_to_json` / `recent_error_log` 为供
//! `lib.rs` FFI 导出直接调用的公开函数，错误日志的路径均不会 panic
//! （锁中毒与序列化失败都有降级返回值）。
//!
//! # 惰性消费说明
//! `push_error` / `recent_error_log` / `ErrorBuffer::push` 等写入侧 API 由
//! todo 25（T3 跳过路径与解码失败接线）接入后消费；接入前保持
//! `#![allow(dead_code)]` 以维持零警告构建（todo 5 验收仅要求导出
//! `native_get_error_log_json` / `native_clear_error_log` 与缓冲语义测试通过）。
#![allow(dead_code)]

use once_cell::sync::Lazy;
use std::collections::VecDeque;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

/// 环形缓冲上限：超出后丢弃最旧条目。
pub const MAX_ERROR_LOG_ENTRIES: usize = 512;

/// 单条错误记录。
///
/// `timestamp` 为 Unix 纪元毫秒（与 `NativeEngine::now_ts` 同口径）。
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ErrorEntry {
    /// 出错文件路径。
    pub path: String,
    /// 探测/解析出的格式标识（小写扩展名或魔数格式名）。
    pub format: String,
    /// 返回给上层的状态码（-2/-3/-6/-7 等）。
    pub status: i32,
    /// 人类可读错误消息。
    pub message: String,
    /// 记录时刻（Unix 毫秒）。
    pub timestamp: u64,
}

/// 环形错误缓冲（FIFO，容量上限 [`MAX_ERROR_LOG_ENTRIES`]）。
#[derive(Default)]
pub struct ErrorBuffer {
    entries: VecDeque<ErrorEntry>,
}

impl ErrorBuffer {
    /// 新建空缓冲。
    pub fn new() -> Self {
        Self::default()
    }

    /// 写入一条记录；已达上限时先丢弃最旧条目再追加。
    pub fn push(&mut self, entry: ErrorEntry) {
        if self.entries.len() >= MAX_ERROR_LOG_ENTRIES {
            self.entries.pop_front();
        }
        self.entries.push_back(entry);
    }

    /// 清空全部记录。
    pub fn clear(&mut self) {
        self.entries.clear();
    }

    /// 序列化为 JSON 数组字符串（serde_json；序列化失败降级为 `"[]"`）。
    pub fn to_json(&self) -> String {
        let values: Vec<serde_json::Value> = self
            .entries
            .iter()
            .map(|e| {
                serde_json::json!({
                    "path": e.path.clone(),
                    "format": e.format.clone(),
                    "status": e.status,
                    "message": e.message.clone(),
                    "timestamp": e.timestamp,
                })
            })
            .collect();
        serde_json::to_string(&values).unwrap_or_else(|_| "[]".to_string())
    }

    /// 返回最近 N 条记录（按写入顺序取末尾 N 条；N=0 或空缓冲返回空）。
    pub fn recent(&self, n: usize) -> Vec<ErrorEntry> {
        let start = self.entries.len().saturating_sub(n);
        self.entries.iter().skip(start).cloned().collect()
    }

    /// 当前记录条数。
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// 缓冲是否为空。
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

/// 全局错误缓冲（惰性初始化，Mutex 保护）。
static ERROR_LOG: Lazy<Mutex<ErrorBuffer>> = Lazy::new(|| Mutex::new(ErrorBuffer::default()));

fn now_ts() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// 记录一条错误入全局缓冲。成功返回 `true`；锁中毒时返回 `false`。
pub fn push_error(path: &str, format: &str, status: i32, message: &str) -> bool {
    let timestamp = now_ts();
    match ERROR_LOG.lock() {
        Ok(mut log) => {
            log.push(ErrorEntry {
                path: path.to_string(),
                format: format.to_string(),
                status,
                message: message.to_string(),
                timestamp,
            });
            true
        }
        Err(_) => false,
    }
}

/// 清空全局错误缓冲。成功返回 `true`；锁中毒时返回 `false`。
pub fn clear_error_log() -> bool {
    match ERROR_LOG.lock() {
        Ok(mut log) => {
            log.clear();
            true
        }
        Err(_) => false,
    }
}

/// 序列化全局错误缓冲为 JSON 数组字符串；锁不可用或序列化失败返回 `"[]"`。
pub fn error_log_to_json() -> String {
    match ERROR_LOG.lock() {
        Ok(log) => log.to_json(),
        Err(_) => "[]".to_string(),
    }
}

/// 返回全局缓冲最近 N 条记录（按写入顺序）。
pub fn recent_error_log(n: usize) -> Vec<ErrorEntry> {
    match ERROR_LOG.lock() {
        Ok(log) => log.recent(n),
        Err(_) => Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(status: i32, path: &str) -> ErrorEntry {
        ErrorEntry {
            path: path.to_string(),
            format: "png".to_string(),
            status,
            message: "decode failed".to_string(),
            timestamp: 1_700_000_000_000,
        }
    }

    #[test]
    fn push_preserves_insertion_order() {
        let mut buf = ErrorBuffer::new();
        buf.push(entry(-1, "a.png"));
        buf.push(entry(-2, "b.png"));
        buf.push(entry(-6, "c.png"));
        assert_eq!(buf.len(), 3);
        let recent = buf.recent(3);
        assert_eq!(recent[0].path, "a.png");
        assert_eq!(recent[1].path, "b.png");
        assert_eq!(recent[2].path, "c.png");
    }

    #[test]
    fn overflow_discards_oldest() {
        let mut buf = ErrorBuffer::new();
        for i in 0..MAX_ERROR_LOG_ENTRIES + 1 {
            buf.push(entry(-1, &format!("f{i}.png")));
        }
        assert_eq!(buf.len(), MAX_ERROR_LOG_ENTRIES);
        let all = buf.recent(MAX_ERROR_LOG_ENTRIES);
        // 最旧（f0）被丢弃，首条为 f1，末条为 f512
        assert_eq!(all.first().map(|e| e.path.as_str()), Some("f1.png"));
        assert_eq!(all.last().map(|e| e.path.as_str()), Some("f512.png"));
    }

    #[test]
    fn recent_limits_to_n() {
        let mut buf = ErrorBuffer::new();
        for i in 0..5 {
            buf.push(entry(-1, &format!("f{i}.png")));
        }
        let two = buf.recent(2);
        assert_eq!(two.len(), 2);
        assert_eq!(two[0].path, "f3.png");
        assert_eq!(two[1].path, "f4.png");
        // n 大于容量时返回全部
        assert_eq!(buf.recent(100).len(), 5);
        // n = 0 返回空
        assert!(buf.recent(0).is_empty());
    }

    #[test]
    fn clear_empties_buffer() {
        let mut buf = ErrorBuffer::new();
        buf.push(entry(-1, "a.png"));
        buf.clear();
        assert!(buf.is_empty());
        assert_eq!(buf.len(), 0);
    }

    #[test]
    fn empty_buffer_serializes_to_empty_array() {
        let buf = ErrorBuffer::new();
        assert_eq!(buf.to_json(), "[]");
    }

    #[test]
    fn to_json_round_trip_fields() {
        let mut buf = ErrorBuffer::new();
        buf.push(ErrorEntry {
            path: r"C:\tmp\broken.png".to_string(),
            format: "png".to_string(),
            status: -6,
            message: "unsupported format".to_string(),
            timestamp: 1_712_500_000_000,
        });
        let json = buf.to_json();
        let value: serde_json::Value =
            serde_json::from_str(&json).expect("JSON 应可被 serde_json 反序列化");
        let arr = value.as_array().expect("应为 JSON 数组");
        assert_eq!(arr.len(), 1);
        let item = &arr[0];
        assert_eq!(item["path"], r"C:\tmp\broken.png");
        assert_eq!(item["format"], "png");
        assert_eq!(item["status"], -6);
        assert_eq!(item["message"], "unsupported format");
        assert_eq!(item["timestamp"], 1_712_500_000_000u64);
    }

    // 全局函数测试：互斥锁串行化，避免 cargo test 并行线程互相干扰共享缓冲。
    static GLOBAL_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn global_push_clear_json_functions_cooperate() {
        let _guard = GLOBAL_LOCK.lock().unwrap();
        assert!(clear_error_log());
        assert!(push_error("x.png", "png", -6, "unsupported"));
        assert!(push_error("y.jpeg", "jpeg", -2, "decode failed"));

        let json = error_log_to_json();
        let value: serde_json::Value =
            serde_json::from_str(&json).expect("全局 JSON 应可被 serde_json 反序列化");
        let arr = value.as_array().expect("应为 JSON 数组");
        assert_eq!(arr.len(), 2);
        assert_eq!(arr[0]["path"], "x.png");
        assert_eq!(arr[0]["status"], -6);
        assert_eq!(arr[1]["format"], "jpeg");
        assert_eq!(arr[1]["status"], -2);

        let recent = recent_error_log(1);
        assert_eq!(recent.len(), 1);
        assert_eq!(recent[0].message, "decode failed");

        assert!(clear_error_log());
        assert!(recent_error_log(0).is_empty());
        assert_eq!(error_log_to_json(), "[]");
    }
}