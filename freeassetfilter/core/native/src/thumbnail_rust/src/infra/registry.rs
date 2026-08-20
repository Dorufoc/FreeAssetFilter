//! 魔数嗅探注册表（todo 7 实现）。
//!
//! 职责：每种格式 2-16 字节魔数注册表（只读文件头 ≤64KB）、魔数嗅探分发到各
//! T1 解码器；支持格式查询导出 `native_get_supported_formats_json`；解码失败/
//! 未注册格式返回 `STATUS_UNSUPPORTED`（上层走 T2/T3），同时保留
//! `legacy_image_decode.rs` 作为 image crate 回退路径接线（直至 todo 26 移除）。
//!
//! **判定策略（测试锁定）**：魔数嗅探优先——魔数命中即按魔数返回格式（扩展名
//! 无关）；魔数未命中时以扩展名兜底——扩展名在注册表内则返回对应格式，否则
//! `None`。伪扩展名文件因此按两层路由：内容是真格式的按真格式走，内容无任何
//! 已知魔数的按扩展名兜底（其解码失败由上层后续 todo 归入 `STATUS_UNSUPPORTED`）。
//!
//! 按 Design Revision 5，本注册表仍为自研实现（管线基础设施例外条款）——
//! 魔数嗅探无引入第三方 crate 的必要，成本低、自研可控。

use std::fs::File;
use std::io::Read;
use std::path::Path;

/// 嗅探时最多读取的文件头字节数（≤64KB 契约；实际各魔数 ≤16 字节）。
const HEADER_READ_LIMIT: u64 = 64 * 1024;

/// 受支持的 14 组格式标识（与 README / thumbnail_manager 常量对齐）。
///
/// `#[repr(usize)]`：判别值即 `FORMAT_SPECS` 表下标，`as usize` 免维护重复 match。
/// 这是纯数据表驱动模块（14 格式 × 魔数/扩展名/JSON 导出 + 计划强制内联单测），
/// 文件总行超过 250 纯行门槛属合理例外（同 infra/resize.rs 的 SIZE_OK 先例）。
#[repr(usize)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FormatId {
    Pnm = 0,
    Qoi,
    Bmp,
    Tga,
    Ico,
    Gif,
    Png,
    Jpeg,
    Tiff,
    Webp,
    Vp8,
    Psd,
    Dds,
    Icns,
}

/// 格式 → (标识字符串, 扩展名列表) 的单一数据表（顺序=枚举判别序=导出 JSON 序）。
/// 数据驱动优于为 id()/extensions() 各写一组 match 臂。
const FORMAT_SPECS: &[(&str, &[&str])] = &[
    ("pnm", &["pbm", "pgm", "ppm", "pnm", "pam"]),
    ("qoi", &["qoi"]),
    ("bmp", &["bmp", "dib"]),
    ("tga", &["tga", "icb", "vda", "vst", "tpic"]),
    ("ico", &["ico", "cur"]),
    ("gif", &["gif"]),
    ("png", &["png"]),
    ("jpeg", &["jpg", "jpeg", "jpe", "jfif"]),
    ("tiff", &["tif", "tiff"]),
    ("webp", &["webp"]),
    ("vp8", &["vp8"]),
    ("psd", &["psd"]),
    ("dds", &["dds"]),
    ("icns", &["icns"]),
];

impl FormatId {
    /// 全量格式标识（顺序即导出 JSON 的 formats 顺序，14 组）。
    pub(crate) const ALL: [FormatId; 14] = [
        FormatId::Pnm,
        FormatId::Qoi,
        FormatId::Bmp,
        FormatId::Tga,
        FormatId::Ico,
        FormatId::Gif,
        FormatId::Png,
        FormatId::Jpeg,
        FormatId::Tiff,
        FormatId::Webp,
        FormatId::Vp8,
        FormatId::Psd,
        FormatId::Dds,
        FormatId::Icns,
    ];

    /// 机器可读格式标识字符串（`native_get_supported_formats_json` 输出）。
    pub(crate) fn id(&self) -> &'static str {
        FORMAT_SPECS[*self as usize].0
    }

    /// 扩展名列表（小写，含点号除外；用于扩展名兜底与导出 JSON）。
    pub(crate) fn extensions(&self) -> &'static [&'static str] {
        FORMAT_SPECS[*self as usize].1
    }
}

/// 魔数嗅探文件头并返回格式；读取失败/魔数未命中且扩展名兜底也未命中返回 `None`。
/// 供 todo 8-22 各 T1 解码器与上层路由接线使用。
#[allow(dead_code)]
// 该函数当前仅被 `#[cfg(test)]` 引用（解码器接线属 todo 8-22），显式标注避免
// dead_code 警告（与 infra/resize.rs 的 box_resize_rgba 同理）。
pub fn sniff_format(path: &str) -> Option<FormatId> {
    let header = read_header(path)?;
    // 空文件（0 字节）永不可解码：即使扩展名在注册表内也不视为已支持。
    if header.is_empty() {
        return None;
    }
    sniff_bytes(&header).or_else(|| ext_to_format(path))
}

/// 路径是否命中注册表（魔数或扩展名兜底任一命中即 true）。
#[allow(dead_code)]
// 同上：上层路由（todo 8-22 / 27）接入前仅测试引用，显式标注避免 dead_code。
pub fn is_supported(path: &str) -> bool {
    sniff_format(path).is_some()
}

/// 序列化全部 14 组格式标识 + 扩展名列表（供 `native_get_supported_formats_json`）。
pub fn supported_formats_json() -> String {
    let formats: Vec<serde_json::Value> = FormatId::ALL
        .iter()
        .map(|f| serde_json::json!({ "id": f.id(), "extensions": f.extensions() }))
        .collect();
    serde_json::to_string(&serde_json::json!({ "formats": formats }))
        .unwrap_or_else(|_| "{}".to_string())
}

/// 打开路径并读取文件头（≤64KB）。返回 `None` 表示文件不存在/不可读/读取失败。
fn read_header(path: &str) -> Option<Vec<u8>> {
    let mut buf = Vec::new();
    File::open(path)
        .ok()?
        .take(HEADER_READ_LIMIT)
        .read_to_end(&mut buf)
        .ok()?;
    Some(buf)
}

/// 对文件头字节执行魔数匹配。TGA 为启发式判定（见 `is_tga_header`）。
fn sniff_bytes(data: &[u8]) -> Option<FormatId> {
    // VP8 有损块（WebP 容器内 `VP8 ` chunk）——比 WebP 容器更具体，先判。
    if data.len() >= 16
        && data.starts_with(b"RIFF")
        && &data[8..12] == b"WEBP"
        && &data[12..16] == b"VP8 "
    {
        return Some(FormatId::Vp8);
    }
    // WebP 容器：RIFF....WEBP（12 字节）。
    if data.len() >= 12 && data.starts_with(b"RIFF") && &data[8..12] == b"WEBP" {
        return Some(FormatId::Webp);
    }
    // PNG：\x89PNG\r\n\x1a\n（8 字节）。
    if data.starts_with(b"\x89PNG\r\n\x1a\n") {
        return Some(FormatId::Png);
    }
    // JPEG：\xFF\xD8（2 字节）。
    if data.starts_with(b"\xff\xd8") {
        return Some(FormatId::Jpeg);
    }
    // GIF：GIF87a / GIF89a（6 字节）。
    if data.starts_with(b"GIF87a") || data.starts_with(b"GIF89a") {
        return Some(FormatId::Gif);
    }
    // BMP：BM / BA（2 字节）。
    if data.starts_with(b"BM") || data.starts_with(b"BA") {
        return Some(FormatId::Bmp);
    }
    // TIFF：II*\x00（小端）/ MM\x00*（大端），各 4 字节。
    if data.len() >= 4 && (&data[..4] == b"II*\x00" || &data[..4] == b"MM\x00*") {
        return Some(FormatId::Tiff);
    }
    if data.starts_with(b"8BPS") {
        return Some(FormatId::Psd);
    }
    if data.starts_with(b"DDS ") {
        return Some(FormatId::Dds);
    }
    if data.starts_with(b"icns") {
        return Some(FormatId::Icns);
    }
    if data.starts_with(b"qoif") {
        return Some(FormatId::Qoi);
    }
    // ICO/CUR：4 字节头——reserved(2)=0、type(2)=1(ICO)/2(CUR)。
    // 注意本规则在 TGA 启发式之前：`[0,0,1,0]`/`[0,0,2,0]` 形态 ICO 优先。
    if data.len() >= 4
        && data[0] == 0
        && data[1] == 0
        && matches!(data[2], 1 | 2)
        && data[3] == 0
    {
        return Some(FormatId::Ico);
    }
    // PNM：'P' 后跟 P1-P7 变体数字（2 字节）。
    if data.len() >= 2 && data[0] == b'P' && (b'1'..=b'7').contains(&data[1]) {
        return Some(FormatId::Pnm);
    }
    // TGA 无真魔数，按头启发式判定（见 is_tga_header 的规则说明）。
    if is_tga_header(data) {
        return Some(FormatId::Tga);
    }
    None
}

/// TGA 启发式判定（计划契约「全 0 或 0x01-0x03 首字节+尾字节」）。
///
/// TGA 18 字节头无固定签名，本注册表采用计划规定的两条规则：
/// 1. **全 0**：首字节（idLength）为 0——无图像 ID，最常见形态；
/// 2. **0x01-0x03 首字节 + 尾字节**：首字节（idLength）为 1-3（带小 ID 块），
///    且判别前缀尾字节（图像类型，字节 2）落在合法取值 1/2/3/9/10/11。
///
/// 已知歧义边界：`[0,0,1,0]`/`[0,0,2,0]` 形态会被 ICO/CUR 规则优先抢占
/// （ICO 检查在 TGA 之前）——ICO 与「全 0 TGA 且图像类型 1/2」天然冲突，
/// 属启发式嗅探的固有歧义，按 ICO 优先记录。
fn is_tga_header(data: &[u8]) -> bool {
    if data.len() < 3 {
        return false;
    }
    if data[0] == 0 {
        return true;
    }
    (0x01..=0x03).contains(&data[0]) && matches!(data[2], 1 | 2 | 3 | 9 | 10 | 11)
}

/// 魔数未命中时的扩展名兜底（小写、去点）。
fn ext_to_format(path: &str) -> Option<FormatId> {
    let ext = Path::new(path)
        .extension()
        .and_then(|s| s.to_str())
        .map(str::to_ascii_lowercase)?;
    FormatId::ALL
        .iter()
        .copied()
        .find(|f| f.extensions().iter().any(|known| known == &ext))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    /// 写临时夹具文件（名称带进程号 + 用例名防并行碰撞），返回绝对路径。
    fn temp_file(name: &str, bytes: &[u8]) -> PathBuf {
        let mut p = std::env::temp_dir();
        p.push(format!("faf_registry_{}_{name}", std::process::id()));
        std::fs::write(&p, bytes).expect("写临时夹具应成功");
        p
    }

    /// 魔数表命中：14 组格式每格式 ≥1 个字节数组头，全部按魔数判定（与文件名无关）。
    #[test]
    fn magic_table_hits_every_format() {
        let cases: &[(&[u8], FormatId)] = &[
            (b"P1\n# c\n1 1\n0", FormatId::Pnm),
            (b"P6\n1 1\n255\n\xff\x00\x00", FormatId::Pnm),
            (b"qoif\x00\x00\x00\x01\x00\x00\x00\x01", FormatId::Qoi),
            (b"BM\x00\x00\x00\x00\x00\x00\x00\x00", FormatId::Bmp),
            (b"BA\x00\x00\x00\x00\x00\x00\x00\x00", FormatId::Bmp),
            // TGA「全 0」：idLength=0、图像类型 10（RLE 真彩）。
            (b"\x00\x00\x0a\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x02\x00\x18\x00",
                FormatId::Tga),
            // TGA「0x01-0x03 首字节 + 尾字节」：idLength=2、图像类型 2。
            (b"\x02\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x02\x00\x18\x00",
                FormatId::Tga),
            (b"\x00\x00\x01\x00\x01\x00\x10\x00\x10\x00\x00\x00\x00\x00", FormatId::Ico),
            (b"\x00\x00\x02\x00\x01\x00\x10\x00\x10\x00\x00\x00\x00\x00", FormatId::Ico),
            (b"GIF87a\x01\x00\x01\x00\x80\x00\x00", FormatId::Gif),
            (b"GIF89a\x01\x00\x01\x00\x80\x00\x00", FormatId::Gif),
            (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", FormatId::Png),
            (b"\xff\xd8\xff\xe0\x00\x10JFIF", FormatId::Jpeg),
            (b"II*\x00\x08\x00\x00\x00", FormatId::Tiff),
            (b"MM\x00*\x00\x00\x00\x08", FormatId::Tiff),
            (b"RIFF\x00\x00\x00\x00WEBP", FormatId::Webp),
            (b"RIFF\x00\x00\x00\x00WEBPVP8 \x00\x00\x00\x00", FormatId::Vp8),
            (b"8BPS\x00\x01\x00\x00\x00\x00\x00\x00", FormatId::Psd),
            (b"DDS \x7c\x00\x00\x00", FormatId::Dds),
            (b"icns\x00\x00\x00\x00", FormatId::Icns),
        ];
        for (i, (head, expected)) in cases.iter().enumerate() {
            let path = temp_file(&format!("magic_{i}.bin"), head);
            assert_eq!(
                sniff_format(path.to_str().unwrap()),
                Some(*expected),
                "魔数表命中失败: 用例 {i} 期望 {expected:?}"
            );
        }
    }

    /// 未命中：无已知魔数且无已知扩展名 → None。
    #[test]
    fn unknown_magic_returns_none() {
        let path = temp_file("unknown.bin", b"NOT-AN-IMAGE-FORMAT-HEADER");
        assert_eq!(sniff_format(path.to_str().unwrap()), None);
        assert!(!is_supported(path.to_str().unwrap()));
    }

    /// 非法路径 / 空文件 → None，不 panic。
    #[test]
    fn invalid_path_and_empty_file_return_none() {
        let missing = std::env::temp_dir().join(format!(
            "faf_registry_missing_{}.png",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&missing);
        assert_eq!(sniff_format(missing.to_str().unwrap()), None, "缺失文件应返回 None");

        let empty = temp_file("empty.png", b"");
        assert_eq!(sniff_format(empty.to_str().unwrap()), None, "空文件应返回 None");
        assert!(!is_supported(empty.to_str().unwrap()), "空文件不可支持");
    }

    /// 伪扩展名判定策略锁定（魔数优先）：
    /// 名为 .png 但内容是 JPEG 魔数 → 按魔数判定为 Jpeg（扩展名不覆盖魔数）。
    #[test]
    fn fake_png_with_jpeg_magic_sniffs_as_jpeg() {
        // 文件名不含组内其他用例（并行线程互踩防护：basename 唯一，扩展名同为 .png）。
        let path = temp_file("fake_magicpng.png", b"\xff\xd8\xff\xe0\x00\x10JFIF...");
        assert_eq!(sniff_format(path.to_str().unwrap()), Some(FormatId::Jpeg));
        assert!(is_supported(path.to_str().unwrap()));
    }

    /// 伪扩展名判定策略锁定（扩展名兜底）：
    /// 名为 .png 但内容无任何已知魔数 → 魔数未命中后按扩展名兜底返回 Png。
    #[test]
    fn fake_png_with_unknown_content_falls_back_to_extension() {
        // 文件名与上述用例区分，避免并行线程写同一临时文件（race）。
        let path = temp_file("fake_text.png", b"definitely not an image at all");
        assert_eq!(sniff_format(path.to_str().unwrap()), Some(FormatId::Png));
        assert!(is_supported(path.to_str().unwrap()));
    }

    /// 已知魔数 + 未知扩展名 → 魔数优先命中。
    #[test]
    fn png_magic_wins_over_unknown_extension() {
        let path = temp_file("dummy.bin", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR");
        assert_eq!(sniff_format(path.to_str().unwrap()), Some(FormatId::Png));
    }

    /// 未命中 + 扩展名不在注册表 → None。
    #[test]
    fn unknown_extension_and_magic_returns_none() {
        let path = temp_file("dummy.exe", b"plain data with no signature");
        assert_eq!(sniff_format(path.to_str().unwrap()), None);
    }

    /// supported_formats_json 含全部 14 组格式标识 + 各自非空扩展名列表。
    #[test]
    fn supported_formats_json_contains_all_fourteen() {
        let payload: serde_json::Value =
            serde_json::from_str(&supported_formats_json()).expect("JSON 应可解析");
        let formats = payload["formats"].as_array().expect("formats 应为数组");
        let ids: Vec<&str> = formats
            .iter()
            .map(|f| f["id"].as_str().expect("id 应为字符串"))
            .collect();
        let expected: Vec<&str> = FormatId::ALL.iter().map(FormatId::id).collect();
        assert_eq!(ids, expected, "formats 标识应覆盖 14 组且顺序稳定");
        for entry in formats {
            let exts = entry["extensions"].as_array().expect("extensions 应为数组");
            assert!(!exts.is_empty(), "每个格式的扩展名列表不得为空");
            let count = FormatId::ALL
                .iter()
                .filter(|f| f.id() == entry["id"].as_str().unwrap())
                .count();
            assert_eq!(count, 1, "格式标识不得重复");
        }
    }

    /// 只读文件头 ≤64KB：超大头长文件仍可命中，且不会全量读入。
    #[test]
    fn header_read_limited_to_64kb() {
        let mut big = vec![0u8; HEADER_READ_LIMIT as usize];
        big[..8].copy_from_slice(b"\x89PNG\r\n\x1a\n");
        big.extend_from_slice(b"trailing payload beyond the limit");
        let path = temp_file("big.png", &big);
        assert_eq!(sniff_format(path.to_str().unwrap()), Some(FormatId::Png));
    }
}