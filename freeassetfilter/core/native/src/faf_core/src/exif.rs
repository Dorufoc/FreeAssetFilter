//! `exif.rs` —— EXIF 元数据解析（todo 6：`faf_parse_exif`）。
//!
//! 语义 oracle：`freeassetfilter/services/file_info_service.py::_collect_exif`
//!（L1032-1069，`(common, rest)` 两组行逐字段一致）+ `_EXIF_DROP_NAMES`
//!（L135）/`_EXIF_COMMON_LABELS`（L112-134）/`_clean_exif_value`
//!（L1011-1021）/`_clean_exif_datetime`（L1024-1029）。
//!
//! todo 1 spike 裁决 **KEEP**：`kamadak-exif` 0.6.1（**BSD-2-Clause**，纯 Rust）。
//!
//! # 实现要点（对拍实测校准，见 `.omo/evidence/rust-hot-path-native-migration/`
//! `task-1-decisions.md` §2 与 `task-6-exif.txt`）
//!
//! 1. **命名映射**：exifread 键为 `"IFD前缀 标签名"`（如 `"Image Make"`、
//!    `"EXIF DateTimeOriginal"`、`"GPS GPSLatitudeRef"`），无冒号 → Python
//!    `short = key.split(":")[-1]` 取整键 → `_EXIF_COMMON_LABELS` 恒不命中、
//!    **`common` 恒空、全部落 `rest`**（oracle 实测）。Rust 侧自建
//!    「(Context, 标签号) → exifread 名称」映射表（`exif_tag_def`/`gps_tag_name`/
//!    `interop_tag_name`），未知标签命名为 `"Tag 0xXXXX"`（与 exifread 一致）。
//! 2. **值格式化**：不用 kamadak `display_value()`（会给 ASCII 加引号、DateTime
//!    转连字符格式），而是取 `Field::value` 原始值按 exifread 语义复刻：
//!    ASCII 去引号取首段、DateTime 保持 `2023:01:15 10:30:00` 冒号格式、
//!    Orientation 等枚举人类化（复刻 exifread `EXIF_TAGS` 字典表）、单值
//!    rational 渲染为 Python `Fraction` 化简式（`28/10 → 14/5`）、多值/列表型
//!    以 `[` 开头被 `_clean_exif_value` 丢弃。`ExifVersion`/`FlashPixVersion` 等
//!    复刻 `make_string` 行为（字节 32..256 → chr）。
//! 3. **IFD 前缀**：`Context::Tiff` 按 `In` 编号 → `Image`/`Thumbnail`/`IFD n`；
//!    `Context::Exif`→`EXIF`、`Context::Gps`→`GPS`、`Context::Interop`→
//!    `Interoperability`。
//! 4. **跳过规则**：exifread `details=False` 的 `IGNORE_TAGS`（`0x02BC` XPM /
//!    `0x927C` MakerNote / `0x9286` UserComment）逐号跳过；`_EXIF_DROP_NAMES`
//!    （小写整键）+ `startswith("maker")`；`short in seen` 大小写敏感去重。
//! 5. **指针标签（已知 diff）**：kamadak 把 `ExifIFDPointer`(0x8769)/
//!    `GPSInfoIFDPointer`(0x8825)/`InteropIFDPointer`(0xa005) 当作结构性导航
//!    **消费掉、不存入 fields**；exifread 则把其打印为普通行（`Image ExifOffset:
//!    <偏移>` / `EXIF GPSInfo: <偏移>`）。故 native 对这些行不输出 —— 这是
//!    对拍中**接受的差异**（≤2 且附原因）。`SubIFDs`(0x014A) 两者都输出，无差异。
//! 6. 损坏/缺失/空文件 → `Err`（FFI 侧 null），不 panic；`continue_on_error`
//!    容错损坏样本（`Error::PartialResult` 取部分结果）。

use std::collections::HashSet;

use exif::{Context, Error as ExifError, Exif, Reader, Tag, Value};

use crate::{STATUS_INVALID_ARG, STATUS_IO_ERROR, STATUS_NOT_FOUND, STATUS_UNSUPPORTED};

/// exifread `details=False` 时跳过（`exifread/core/tags/__init__.py` `IGNORE_TAGS`）。
const IGNORE_TAG_NUMBERS: [u16; 3] = [0x02BC, 0x927C, 0x9286];

/// `file_info_service._EXIF_DROP_NAMES`（L135-138）精确复刻。
const EXIF_DROP_NAMES: [&str; 7] = [
    "jpegthumbnail",
    "thumbnailequipment",
    "thumbnailimagesize",
    "thumbnailoffset",
    "thumbnailbytes",
    "exifthumbnail",
    "makernote",
];

/// `file_info_service._EXIF_COMMON_LABELS`（L112-134）精确复刻（oracle 实测恒不命中）。
const COMMON_LABELS: [(&str, &str); 20] = [
    ("Make", "相机厂商"),
    ("Model", "相机型号"),
    ("LensModel", "镜头型号"),
    ("DateTimeOriginal", "拍摄时间"),
    ("DateTime", "文件时间"),
    ("ExposureTime", "快门速度"),
    ("FNumber", "光圈值"),
    ("ExposureBiasValue", "曝光补偿"),
    ("ISOSpeedRatings", "ISO"),
    ("FocalLength", "焦距"),
    ("FocalLengthIn35mmFilm", "等效焦距"),
    ("WhiteBalance", "白平衡"),
    ("Flash", "闪光灯"),
    ("MeteringMode", "测光模式"),
    ("ExposureMode", "曝光模式"),
    ("ExposureProgram", "曝光程序"),
    ("SceneCaptureType", "场景类型"),
    ("Orientation", "方向"),
    ("Software", "处理软件"),
    ("ColorSpace", "色彩空间"),
];

/// 标签的 exifread 展示种类：普通 / 枚举人类化 / make_string 处理。
#[derive(Clone, Copy, Debug)]
enum TagKind {
    Plain,
    Enum(&'static [(u32, &'static str)]),
    MakeString,
    MakeStringUc,
}

#[derive(Clone, Copy, Debug)]
struct TagDef {
    name: &'static str,
    kind: TagKind,
}

// ---------------------------------------------------------------------------
// exifread EXIF_TAGS 枚举人类化表（逐字复刻 `exifread/tags/exif.py`）
// ---------------------------------------------------------------------------

const SUBFILE_TYPE_ENUM: &[(u32, &str)] = &[
    (0x00000000, "Full-resolution Image"),
    (0x00000001, "Reduced-resolution image"),
    (0x00000002, "Single page of multi-page image"),
    (0x00000003, "Single page of multi-page reduced-resolution image"),
    (0x00000004, "Transparency mask"),
    (0x00000005, "Transparency mask of reduced-resolution image"),
    (0x00000006, "Transparency mask of multi-page image"),
    (0x00000007, "Transparency mask of reduced-resolution multi-page image"),
    (0x00010001, "Alternate reduced-resolution image"),
    (0xFFFFFFFF, "invalid "),
];

const OLD_SUBFILE_TYPE_ENUM: &[(u32, &str)] = &[
    (1, "Full-resolution image"),
    (2, "Reduced-resolution image"),
    (3, "Single page of multi-page image"),
];

const COMPRESSION_ENUM: &[(u32, &str)] = &[
    (1, "Uncompressed"),
    (2, "CCITT 1D"),
    (3, "T4/Group 3 Fax"),
    (4, "T6/Group 4 Fax"),
    (5, "LZW"),
    (6, "JPEG (old-style)"),
    (7, "JPEG"),
    (8, "Adobe Deflate"),
    (9, "JBIG B&W"),
    (10, "JBIG Color"),
    (32766, "Next"),
    (32769, "Epson ERF Compressed"),
    (32771, "CCIRLEW"),
    (32773, "PackBits"),
    (32809, "Thunderscan"),
    (32895, "IT8CTPAD"),
    (32896, "IT8LW"),
    (32897, "IT8MP"),
    (32898, "IT8BL"),
    (32908, "PixarFilm"),
    (32909, "PixarLog"),
    (32946, "Deflate"),
    (32947, "DCS"),
    (34661, "JBIG"),
    (34676, "SGILog"),
    (34677, "SGILog24"),
    (34712, "JPEG 2000"),
    (34713, "Nikon NEF Compressed"),
    (65000, "Kodak DCR Compressed"),
    (65535, "Pentax PEF Compressed"),
];

const ORIENTATION_ENUM: &[(u32, &str)] = &[
    (1, "Horizontal (normal)"),
    (2, "Mirrored horizontal"),
    (3, "Rotated 180"),
    (4, "Mirrored vertical"),
    (5, "Mirrored horizontal then rotated 90 CCW"),
    (6, "Rotated 90 CW"),
    (7, "Mirrored horizontal then rotated 90 CW"),
    (8, "Rotated 90 CCW"),
];

const GRAY_RESPONSE_UNIT_ENUM: &[(u32, &str)] = &[
    (1, "0.1"),
    (2, "0.001"),
    (3, "0.0001"),
    (4, "1e-05"),
    (5, "1e-06"),
];

const RESOLUTION_UNIT_ENUM: &[(u32, &str)] = &[
    (1, "Not Absolute"),
    (2, "Pixels/Inch"),
    (3, "Pixels/Centimeter"),
];

const PREDICTOR_ENUM: &[(u32, &str)] = &[(1, "None"), (2, "Horizontal differencing")];

const CLEAN_FAX_DATA_ENUM: &[(u32, &str)] = &[(0, "Clean"), (1, "Regenerated"), (2, "Unclean")];

const INK_SET_ENUM: &[(u32, &str)] = &[(1, "CMYK"), (2, "Not CMYK")];

const EXTRA_SAMPLES_ENUM: &[(u32, &str)] = &[
    (0, "Unspecified"),
    (1, "Associated Alpha"),
    (2, "Unassociated Alpha"),
];

const SAMPLE_FORMAT_ENUM: &[(u32, &str)] = &[
    (1, "Unsigned"),
    (2, "Signed"),
    (3, "Float"),
    (4, "Undefined"),
    (5, "Complex int"),
    (6, "Complex float"),
];

const YCBCR_POSITIONING_ENUM: &[(u32, &str)] = &[(1, "Centered"), (2, "Co-sited")];

const EXPOSURE_PROGRAM_ENUM: &[(u32, &str)] = &[
    (0, "Unidentified"),
    (1, "Manual"),
    (2, "Program Normal"),
    (3, "Aperture Priority"),
    (4, "Shutter Priority"),
    (5, "Program Creative"),
    (6, "Program Action"),
    (7, "Portrait Mode"),
    (8, "Landscape Mode"),
];

const SENSITIVITY_TYPE_ENUM: &[(u32, &str)] = &[
    (0, "Unknown"),
    (1, "Standard Output Sensitivity"),
    (2, "Recommended Exposure Index"),
    (3, "ISO Speed"),
    (4, "Standard Output Sensitivity and Recommended Exposure Index"),
    (5, "Standard Output Sensitivity and ISO Speed"),
    (6, "Recommended Exposure Index and ISO Speed"),
    (
        7,
        "Standard Output Sensitivity, Recommended Exposure Index and ISO Speed",
    ),
];

const COMPONENTS_CONFIGURATION_ENUM: &[(u32, &str)] = &[
    (0, ""),
    (1, "Y"),
    (2, "Cb"),
    (3, "Cr"),
    (4, "Red"),
    (5, "Green"),
    (6, "Blue"),
];

const METERING_MODE_ENUM: &[(u32, &str)] = &[
    (0, "Unidentified"),
    (1, "Average"),
    (2, "CenterWeightedAverage"),
    (3, "Spot"),
    (4, "MultiSpot"),
    (5, "Pattern"),
    (6, "Partial"),
    (255, "other"),
];

const LIGHT_SOURCE_ENUM: &[(u32, &str)] = &[
    (0, "Unknown"),
    (1, "Daylight"),
    (2, "Fluorescent"),
    (3, "Tungsten (incandescent light)"),
    (4, "Flash"),
    (9, "Fine weather"),
    (10, "Cloudy weather"),
    (11, "Shade"),
    (12, "Daylight fluorescent (D 5700 - 7100K)"),
    (13, "Day white fluorescent (N 4600 - 5400K)"),
    (14, "Cool white fluorescent (W 3900 - 4500K)"),
    (15, "White fluorescent (WW 3200 - 3700K)"),
    (17, "Standard light A"),
    (18, "Standard light B"),
    (19, "Standard light C"),
    (20, "D55"),
    (21, "D65"),
    (22, "D75"),
    (23, "D50"),
    (24, "ISO studio tungsten"),
    (255, "other light source"),
];

const FLASH_ENUM: &[(u32, &str)] = &[
    (0, "Flash did not fire"),
    (1, "Flash fired"),
    (5, "Strobe return light not detected"),
    (7, "Strobe return light detected"),
    (9, "Flash fired, compulsory flash mode"),
    (13, "Flash fired, compulsory flash mode, return light not detected"),
    (15, "Flash fired, compulsory flash mode, return light detected"),
    (16, "Flash did not fire, compulsory flash mode"),
    (24, "Flash did not fire, auto mode"),
    (25, "Flash fired, auto mode"),
    (29, "Flash fired, auto mode, return light not detected"),
    (31, "Flash fired, auto mode, return light detected"),
    (32, "No flash function"),
    (65, "Flash fired, red-eye reduction mode"),
    (69, "Flash fired, red-eye reduction mode, return light not detected"),
    (71, "Flash fired, red-eye reduction mode, return light detected"),
    (73, "Flash fired, compulsory flash mode, red-eye reduction mode"),
    (
        77,
        "Flash fired, compulsory flash mode, red-eye reduction mode, return light not detected",
    ),
    (79, "Flash fired, compulsory flash mode, red-eye reduction mode, return light detected"),
    (89, "Flash fired, auto mode, red-eye reduction mode"),
    (93, "Flash fired, auto mode, return light not detected, red-eye reduction mode"),
    (95, "Flash fired, auto mode, return light detected, red-eye reduction mode"),
];

const COLOR_SPACE_ENUM: &[(u32, &str)] = &[
    (1, "sRGB"),
    (2, "Adobe RGB"),
    (65535, "Uncalibrated"),
];

const SENSING_METHOD_ENUM: &[(u32, &str)] = &[
    (1, "Not defined"),
    (2, "One-chip color area"),
    (3, "Two-chip color area"),
    (4, "Three-chip color area"),
    (5, "Color sequential area"),
    (7, "Trilinear"),
    (8, "Color sequential linear"),
];

const FILE_SOURCE_ENUM: &[(u32, &str)] = &[
    (1, "Film Scanner"),
    (2, "Reflection Print Scanner"),
    (3, "Digital Camera"),
];

const SCENE_TYPE_ENUM: &[(u32, &str)] = &[(1, "Directly Photographed")];

const CUSTOM_RENDERED_ENUM: &[(u32, &str)] = &[(0, "Normal"), (1, "Custom")];

const EXPOSURE_MODE_ENUM: &[(u32, &str)] = &[
    (0, "Auto Exposure"),
    (1, "Manual Exposure"),
    (2, "Auto Bracket"),
];

const WHITE_BALANCE_ENUM: &[(u32, &str)] = &[(0, "Auto"), (1, "Manual")];

const SCENE_CAPTURE_TYPE_ENUM: &[(u32, &str)] = &[
    (0, "Standard"),
    (1, "Landscape"),
    (2, "Portrait"),
    (3, "Night"),
];

const GAIN_CONTROL_ENUM: &[(u32, &str)] = &[
    (0, "None"),
    (1, "Low gain up"),
    (2, "High gain up"),
    (3, "Low gain down"),
    (4, "High gain down"),
];

const CONTRAST_ENUM: &[(u32, &str)] = &[(0, "Normal"), (1, "Soft"), (2, "Hard")];

const SATURATION_ENUM: &[(u32, &str)] = &[(0, "Normal"), (1, "Soft"), (2, "Hard")];

const SHARPNESS_ENUM: &[(u32, &str)] = &[(0, "Normal"), (1, "Soft"), (2, "Hard")];

const SUBJECT_DISTANCE_RANGE_ENUM: &[(u32, &str)] = &[
    (0, "Unknown"),
    (1, "Macro"),
    (2, "Close view"),
    (3, "Distant view"),
];

/// exifread `EXIF_TAGS`（Tiff/Exif 两个上下文共用同一张表）：标签号 → 名称 + 展示种类。
///
/// 返回 `None` 表示 exifread 无此标签 → 名称按 `"Tag 0xXXXX"`（大写 hex 四位）。
fn exif_tag_def(tag: u16) -> Option<TagDef> {
    let def = |name: &'static str, kind: TagKind| TagDef { name, kind };
    let plain = |name: &'static str| TagDef { name, kind: TagKind::Plain };
    Some(match tag {
        0x00FE => def("SubfileType", TagKind::Enum(SUBFILE_TYPE_ENUM)),
        0x00FF => def("OldSubfileType", TagKind::Enum(OLD_SUBFILE_TYPE_ENUM)),
        0x0100 => plain("ImageWidth"),
        0x0101 => plain("ImageLength"),
        0x0102 => plain("BitsPerSample"),
        0x0103 => def("Compression", TagKind::Enum(COMPRESSION_ENUM)),
        0x0106 => plain("PhotometricInterpretation"),
        0x0107 => plain("Thresholding"),
        0x0108 => plain("CellWidth"),
        0x0109 => plain("CellLength"),
        0x010A => plain("FillOrder"),
        0x010D => plain("DocumentName"),
        0x010E => plain("ImageDescription"),
        0x010F => plain("Make"),
        0x0110 => plain("Model"),
        0x0111 => plain("StripOffsets"),
        0x0112 => def("Orientation", TagKind::Enum(ORIENTATION_ENUM)),
        0x0115 => plain("SamplesPerPixel"),
        0x0116 => plain("RowsPerStrip"),
        0x0117 => plain("StripByteCounts"),
        0x0118 => plain("MinSampleValue"),
        0x0119 => plain("MaxSampleValue"),
        0x011A => plain("XResolution"),
        0x011B => plain("YResolution"),
        0x011C => plain("PlanarConfiguration"),
        0x011D => def("PageName", TagKind::MakeString),
        0x011E => plain("XPosition"),
        0x011F => plain("YPosition"),
        0x0122 => def("GrayResponseUnit", TagKind::Enum(GRAY_RESPONSE_UNIT_ENUM)),
        0x0123 => plain("GrayResponseCurve"),
        0x0124 => plain("T4Options"),
        0x0125 => plain("T6Options"),
        0x0128 => def("ResolutionUnit", TagKind::Enum(RESOLUTION_UNIT_ENUM)),
        0x0129 => plain("PageNumber"),
        0x012C => plain("ColorResponseUnit"),
        0x012D => plain("TransferFunction"),
        0x0131 => plain("Software"),
        0x0132 => plain("DateTime"),
        0x013B => plain("Artist"),
        0x013C => plain("HostComputer"),
        0x013D => def("Predictor", TagKind::Enum(PREDICTOR_ENUM)),
        0x013E => plain("WhitePoint"),
        0x013F => plain("PrimaryChromaticities"),
        0x0140 => plain("ColorMap"),
        0x0141 => plain("HalftoneHints"),
        0x0142 => plain("TileWidth"),
        0x0143 => plain("TileLength"),
        0x0144 => plain("TileOffsets"),
        0x0145 => plain("TileByteCounts"),
        0x0146 => plain("BadFaxLines"),
        0x0147 => def("CleanFaxData", TagKind::Enum(CLEAN_FAX_DATA_ENUM)),
        0x014A => plain("SubIFDs"),
        0x0148 => plain("ConsecutiveBadFaxLines"),
        0x014C => def("InkSet", TagKind::Enum(INK_SET_ENUM)),
        0x014D => plain("InkNames"),
        0x014E => plain("NumberofInks"),
        0x0150 => plain("DotRange"),
        0x0151 => plain("TargetPrinter"),
        0x0152 => def("ExtraSamples", TagKind::Enum(EXTRA_SAMPLES_ENUM)),
        0x0153 => def("SampleFormat", TagKind::Enum(SAMPLE_FORMAT_ENUM)),
        0x0154 => plain("SMinSampleValue"),
        0x0155 => plain("SMaxSampleValue"),
        0x0156 => plain("TransferRange"),
        0x0157 => plain("ClipPath"),
        0x015B => plain("JPEGTables"),
        0x0200 => plain("JPEGProc"),
        0x0201 => plain("JPEGInterchangeFormat"),
        0x0202 => plain("JPEGInterchangeFormatLength"),
        0x0211 => plain("YCbCrCoefficients"),
        0x0212 => plain("YCbCrSubSampling"),
        0x0213 => def("YCbCrPositioning", TagKind::Enum(YCBCR_POSITIONING_ENUM)),
        0x0214 => plain("ReferenceBlackWhite"),
        0x02BC => plain("ApplicationNotes"),
        0x4746 => plain("Rating"),
        0x828D => plain("CFARepeatPatternDim"),
        0x828E => plain("CFAPattern"),
        0x828F => plain("BatteryLevel"),
        0x8298 => plain("Copyright"),
        0x829A => plain("ExposureTime"),
        0x829D => plain("FNumber"),
        0x83BB => plain("IPTC/NAA"),
        0x8769 => plain("ExifOffset"),
        0x8773 => plain("InterColorProfile"),
        0x8822 => def("ExposureProgram", TagKind::Enum(EXPOSURE_PROGRAM_ENUM)),
        0x8824 => plain("SpectralSensitivity"),
        0x8825 => plain("GPSInfo"),
        0x8827 => plain("ISOSpeedRatings"),
        0x8828 => plain("OECF"),
        0x8829 => plain("Interlace"),
        0x882A => plain("TimeZoneOffset"),
        0x882B => plain("SelfTimerMode"),
        0x8830 => def("SensitivityType", TagKind::Enum(SENSITIVITY_TYPE_ENUM)),
        0x8832 => plain("RecommendedExposureIndex"),
        0x8833 => plain("ISOSpeed"),
        0x9000 => def("ExifVersion", TagKind::MakeString),
        0x9003 => plain("DateTimeOriginal"),
        0x9004 => plain("DateTimeDigitized"),
        0x9010 => plain("OffsetTime"),
        0x9011 => plain("OffsetTimeOriginal"),
        0x9012 => plain("OffsetTimeDigitized"),
        0x9101 => def("ComponentsConfiguration", TagKind::Enum(COMPONENTS_CONFIGURATION_ENUM)),
        0x9102 => plain("CompressedBitsPerPixel"),
        0x9201 => plain("ShutterSpeedValue"),
        0x9202 => plain("ApertureValue"),
        0x9203 => plain("BrightnessValue"),
        0x9204 => plain("ExposureBiasValue"),
        0x9205 => plain("MaxApertureValue"),
        0x9206 => plain("SubjectDistance"),
        0x9207 => def("MeteringMode", TagKind::Enum(METERING_MODE_ENUM)),
        0x9208 => def("LightSource", TagKind::Enum(LIGHT_SOURCE_ENUM)),
        0x9209 => def("Flash", TagKind::Enum(FLASH_ENUM)),
        0x920A => plain("FocalLength"),
        0x920B => plain("FlashEnergy"),
        0x920C => plain("SpatialFrequencyResponse"),
        0x920D => plain("Noise"),
        0x9211 => plain("ImageNumber"),
        0x9212 => plain("SecurityClassification"),
        0x9213 => plain("ImageHistory"),
        0x9214 => plain("SubjectArea"),
        0x9215 => plain("ExposureIndex"),
        0x9216 => plain("TIFF/EPStandardID"),
        0x927C => plain("MakerNote"),
        0x9286 => def("UserComment", TagKind::MakeStringUc),
        0x9290 => plain("SubSecTime"),
        0x9291 => plain("SubSecTimeOriginal"),
        0x9292 => plain("SubSecTimeDigitized"),
        0x9C9B => plain("XPTitle"),
        0x9C9C => plain("XPComment"),
        0x9C9D => def("XPAuthor", TagKind::MakeString),
        0x9C9E => plain("XPKeywords"),
        0x9C9F => plain("XPSubject"),
        0xA000 => def("FlashPixVersion", TagKind::MakeString),
        0xA001 => def("ColorSpace", TagKind::Enum(COLOR_SPACE_ENUM)),
        0xA002 => plain("ExifImageWidth"),
        0xA003 => plain("ExifImageLength"),
        0xA004 => plain("RelatedSoundFile"),
        0xA005 => plain("InteroperabilityOffset"),
        0xA20B => plain("FlashEnergy"),
        0xA20C => plain("SpatialFrequencyResponse"),
        0xA20E => plain("FocalPlaneXResolution"),
        0xA20F => plain("FocalPlaneYResolution"),
        0xA210 => plain("FocalPlaneResolutionUnit"),
        0xA214 => plain("SubjectLocation"),
        0xA215 => plain("ExposureIndex"),
        0xA217 => def("SensingMethod", TagKind::Enum(SENSING_METHOD_ENUM)),
        0xA300 => def("FileSource", TagKind::Enum(FILE_SOURCE_ENUM)),
        0xA301 => def("SceneType", TagKind::Enum(SCENE_TYPE_ENUM)),
        0xA302 => plain("CVAPattern"),
        0xA401 => def("CustomRendered", TagKind::Enum(CUSTOM_RENDERED_ENUM)),
        0xA402 => def("ExposureMode", TagKind::Enum(EXPOSURE_MODE_ENUM)),
        0xA403 => def("WhiteBalance", TagKind::Enum(WHITE_BALANCE_ENUM)),
        0xA404 => plain("DigitalZoomRatio"),
        0xA405 => plain("FocalLengthIn35mmFilm"),
        0xA406 => def("SceneCaptureType", TagKind::Enum(SCENE_CAPTURE_TYPE_ENUM)),
        0xA407 => def("GainControl", TagKind::Enum(GAIN_CONTROL_ENUM)),
        0xA408 => def("Contrast", TagKind::Enum(CONTRAST_ENUM)),
        0xA409 => def("Saturation", TagKind::Enum(SATURATION_ENUM)),
        0xA40A => def("Sharpness", TagKind::Enum(SHARPNESS_ENUM)),
        0xA40B => plain("DeviceSettingDescription"),
        0xA40C => def("SubjectDistanceRange", TagKind::Enum(SUBJECT_DISTANCE_RANGE_ENUM)),
        0xA420 => plain("ImageUniqueID"),
        0xA430 => plain("CameraOwnerName"),
        0xA431 => plain("BodySerialNumber"),
        0xA432 => plain("LensSpecification"),
        0xA433 => plain("LensMake"),
        0xA434 => plain("LensModel"),
        0xA435 => plain("LensSerialNumber"),
        0xA500 => plain("Gamma"),
        0xC4A5 => plain("PrintIM"),
        0xC61A => plain("BlackLevel"),
        0xEA1C => plain("Padding"),
        0xEA1D => plain("OffsetSchema"),
        0xFDE8 => plain("OwnerName"),
        0xFDE9 => plain("SerialNumber"),
        _ => return None,
    })
}

/// exifread `GPS_TAGS`（`exifread/tags/exif.py`，全部为普通标签）。
fn gps_tag_name(tag: u16) -> Option<&'static str> {
    Some(match tag {
        0x0000 => "GPSVersionID",
        0x0001 => "GPSLatitudeRef",
        0x0002 => "GPSLatitude",
        0x0003 => "GPSLongitudeRef",
        0x0004 => "GPSLongitude",
        0x0005 => "GPSAltitudeRef",
        0x0006 => "GPSAltitude",
        0x0007 => "GPSTimeStamp",
        0x0008 => "GPSSatellites",
        0x0009 => "GPSStatus",
        0x000A => "GPSMeasureMode",
        0x000B => "GPSDOP",
        0x000C => "GPSSpeedRef",
        0x000D => "GPSSpeed",
        0x000E => "GPSTrackRef",
        0x000F => "GPSTrack",
        0x0010 => "GPSImgDirectionRef",
        0x0011 => "GPSImgDirection",
        0x0012 => "GPSMapDatum",
        0x0013 => "GPSDestLatitudeRef",
        0x0014 => "GPSDestLatitude",
        0x0015 => "GPSDestLongitudeRef",
        0x0016 => "GPSDestLongitude",
        0x0017 => "GPSDestBearingRef",
        0x0018 => "GPSDestBearing",
        0x0019 => "GPSDestDistanceRef",
        0x001A => "GPSDestDistance",
        0x001B => "GPSProcessingMethod",
        0x001C => "GPSAreaInformation",
        0x001D => "GPSDate",
        0x001E => "GPSDifferential",
        _ => return None,
    })
}

/// exifread `INTEROP_TAGS`（`exifread/tags/exif.py`，全部为普通标签）。
fn interop_tag_name(tag: u16) -> Option<&'static str> {
    Some(match tag {
        0x0001 => "InteroperabilityIndex",
        0x0002 => "InteroperabilityVersion",
        0x1000 => "RelatedImageFileFormat",
        0x1001 => "RelatedImageWidth",
        0x1002 => "RelatedImageLength",
        _ => return None,
    })
}

/// exifread 键：`"IFD前缀 标签名"`。
fn exifread_key(tag: &Tag, ifd_idx: u16) -> String {
    let name = match tag.context() {
        Context::Tiff | Context::Exif => match exif_tag_def(tag.number()) {
            Some(d) => d.name.to_string(),
            None => unknown_tag_name(tag.number()),
        },
        Context::Gps => match gps_tag_name(tag.number()) {
            Some(n) => n.to_string(),
            None => unknown_tag_name(tag.number()),
        },
        Context::Interop => match interop_tag_name(tag.number()) {
            Some(n) => n.to_string(),
            None => unknown_tag_name(tag.number()),
        },
        // Context 为非穷尽枚举；未来变体按未知标签处理。
        _ => unknown_tag_name(tag.number()),
    };
    let prefix = match tag.context() {
        Context::Tiff => match ifd_idx {
            0 => "Image".to_string(),
            1 => "Thumbnail".to_string(),
            n => format!("IFD {}", n),
        },
        Context::Exif => "EXIF".to_string(),
        Context::Gps => "GPS".to_string(),
        Context::Interop => "Interoperability".to_string(),
        _ => "Image".to_string(),
    };
    format!("{} {}", prefix, name)
}

/// 未知标签名（exifread `f"Tag 0x{tag:04X}"`）。
fn unknown_tag_name(tag: u16) -> String {
    format!("Tag 0x{:04X}", tag)
}

/// 标签展示种类（Tiff/Exif 上下文查 `EXIF_TAGS`，其余为普通）。
fn tag_kind(tag: &Tag) -> TagKind {
    match tag.context() {
        Context::Tiff | Context::Exif => exif_tag_def(tag.number())
            .map(|d| d.kind)
            .unwrap_or(TagKind::Plain),
        _ => TagKind::Plain,
    }
}

// ---------------------------------------------------------------------------
// 值格式化（复刻 exifread `_get_printable_for_field` + 各 helper）
// ---------------------------------------------------------------------------

/// 依 exifread 语义把原始 `Value` 渲染为 printable 文本。
///
/// `None` 仅用于 kamadak 未解析的类型（`Value::Unknown`，exifread 对未知类型
/// 在非 strict 模式下直接跳过该标签）。
fn exifread_printable(tag: &Tag, value: &Value) -> Option<String> {
    let base = match value {
        Value::Unknown(..) => return None,
        // ASCII 恒走 else 分支：printable = str(values)（解码后的字符串）。
        Value::Ascii(segments) => {
            let first: &[u8] = match segments.first() {
                Some(s) => s.as_slice(),
                None => &[],
            };
            Some(decode_ascii(first))
        }
        _ => {
            let len = value_len(value);
            if len == 1 {
                Some(single_value_str(value))
            } else {
                // count>1 → Python `str(list)` 以 `[` 开头，被 `_clean_exif_value`
                // 丢弃；无需精确复刻列表内容。
                Some("[...]".to_string())
            }
        }
    }?;
    Some(match tag_kind(tag) {
        TagKind::Plain => base,
        TagKind::Enum(table) => match enum_uint_values(value) {
            Some(vals) => {
                let mut s = String::new();
                for v in vals {
                    match table.iter().find(|(k, _)| *k as u64 == v) {
                        Some((_, text)) => s.push_str(text),
                        None => s.push_str(&v.to_string()),
                    }
                }
                s
            }
            None => base,
        },
        TagKind::MakeString => make_string_value(value, &base),
        TagKind::MakeStringUc => make_string_uc_value(value, &base),
    })
}

/// 字段值的元素个数（ASCII 之外等价于 exifread 的 `count`）。
fn value_len(value: &Value) -> usize {
    match value {
        Value::Byte(v) => v.len(),
        Value::Ascii(_) => 0, // ASCII 单独处理
        Value::Short(v) => v.len(),
        Value::Long(v) => v.len(),
        Value::Rational(v) => v.len(),
        Value::SByte(v) => v.len(),
        Value::Undefined(v, _) => v.len(),
        Value::SShort(v) => v.len(),
        Value::SLong(v) => v.len(),
        Value::SRational(v) => v.len(),
        Value::Float(v) => v.len(),
        Value::Double(v) => v.len(),
        Value::Unknown(_, cnt, _) => *cnt as usize,
    }
}

/// `count == 1` 非 ASCII：`printable = str(values[0])`。
fn single_value_str(value: &Value) -> String {
    match value {
        Value::Byte(v) => v[0].to_string(),
        Value::Short(v) => v[0].to_string(),
        Value::Long(v) => v[0].to_string(),
        Value::SByte(v) => v[0].to_string(),
        Value::SShort(v) => v[0].to_string(),
        Value::SLong(v) => v[0].to_string(),
        Value::Rational(v) => fraction_str(v[0].num as i64, v[0].denom as i64),
        Value::SRational(v) => fraction_str(v[0].num as i64, v[0].denom as i64),
        Value::Undefined(v, _) => v[0].to_string(),
        // exifread 对 FLOAT/DOUBLE 追加 struct.unpack 的 tuple，str 为 "(1.5,)"。
        Value::Float(v) => format!("({},)", py_float_str(v[0] as f64)),
        Value::Double(v) => format!("({},)", py_float_str(v[0])),
        // ASCII/Unknown 在调用处已单独处理。
        Value::Ascii(_) | Value::Unknown(..) => String::new(),
    }
}

/// 枚举人类化：把 Byte/Short/Long/Undefined 值迭代为 u64。
fn enum_uint_values(value: &Value) -> Option<Vec<u64>> {
    match value {
        Value::Byte(v) => Some(v.iter().map(|&x| x as u64).collect()),
        Value::Short(v) => Some(v.iter().map(|&x| x as u64).collect()),
        Value::Long(v) => Some(v.iter().map(|&x| x as u64).collect()),
        Value::Undefined(v, _) => Some(v.iter().map(|&x| x as u64).collect()),
        _ => None,
    }
}

/// ASCII 首段解码：exifread 用 UTF-8；失败时保留 bytes → Python `str(bytes)`
/// 的 `b'...'` 表示。
fn decode_ascii(seg: &[u8]) -> String {
    match std::str::from_utf8(seg) {
        Ok(s) => s.to_string(),
        Err(_) => py_bytes_repr(seg),
    }
}

/// Python `str(bytes)`（`b'...'`）复刻。
fn py_bytes_repr(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() + 2);
    out.push_str("b'");
    for &byte in bytes {
        match byte {
            b'\n' => out.push_str("\\n"),
            b'\r' => out.push_str("\\r"),
            b'\t' => out.push_str("\\t"),
            b'\\' => out.push_str("\\\\"),
            b'\'' => out.push_str("\\'"),
            0x20..=0x7E => out.push(byte as char),
            _ => out.push_str(&format!("\\x{:02x}", byte)),
        }
    }
    out.push('\'');
    out
}

/// Python `make_string`（`exifread/tags/str_utils.py`）：字节 32..256 → chr。
fn make_string_ints(bytes: &[u8]) -> String {
    let mut s = String::new();
    for &b in bytes {
        if (32..=255).contains(&b) {
            s.push(b as char);
        }
    }
    if s.is_empty() {
        let joined: String = bytes.iter().map(|x| x.to_string()).collect();
        if joined.chars().all(|c| c == '0') {
            return String::new();
        }
        s = joined;
    }
    strip_spaces_nulls(&s)
}

/// Python `make_string` 对已解码字符串：迭代 str 抛 TypeError 后回退
/// `str(seq)` 再 `.strip(" \x00")`。
fn strip_spaces_nulls(s: &str) -> String {
    s.trim_matches(|c: char| c == ' ' || c == '\0').to_string()
}

/// `make_string` 按值类型分派。
fn make_string_value(value: &Value, base: &str) -> String {
    match value {
        Value::Undefined(v, _) => make_string_ints(v),
        Value::Byte(v) => make_string_ints(v),
        Value::Ascii(_) => strip_spaces_nulls(base),
        _ => base.to_string(),
    }
}

/// `make_string_uc`（`exifread/tags/str_utils.py`；UserComment 已被 IGNORE 跳过，
/// 保留实现以防未来接线需要）。
fn make_string_uc_value(value: &Value, base: &str) -> String {
    match value {
        Value::Undefined(v, _) | Value::Byte(v) => {
            let head = make_string_ints(&v[..v.len().min(8)]);
            if ["ASCII", "UNICODE", "JIS", ""].contains(&head.to_uppercase().as_str()) {
                make_string_ints(&v[v.len().min(8)..])
            } else {
                make_string_ints(v)
            }
        }
        _ => strip_spaces_nulls(base),
    }
}

/// Python `Fraction` 化简式字符串（`str(Ratio)`）。
fn fraction_str(num: i64, den: i64) -> String {
    // Fraction(num, 0) 抛 ZeroDivisionError → Ratio 兜底为 Fraction() = 0。
    if den == 0 {
        return "0".to_string();
    }
    let (n, d) = if den < 0 { (-num, -den) } else { (num, den) };
    if n == 0 {
        return "0".to_string();
    }
    let g = gcd(n.unsigned_abs(), d as u64) as i64;
    let n = n / g;
    let d = d / g;
    if d == 1 {
        format!("{}", n)
    } else {
        format!("{}/{}", n, d)
    }
}

/// 最大公约数（Python `math.gcd`）。
fn gcd(mut a: u64, mut b: u64) -> u64 {
    while b != 0 {
        let t = b;
        b = a % b;
        a = t;
    }
    a
}

/// Python `str(float)` 复刻（最短往返 + 大/小值指数记法；样本中不涉及，防御性实现）。
fn py_float_str(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf".to_string() } else { "-inf".to_string() };
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0.0".to_string() } else { "0.0".to_string() };
    }
    let a = x.abs();
    if !(1e-4..1e16).contains(&a) {
        let s = format!("{:e}", x);
        let (mant, exp) = match s.split_once('e') {
            Some(pair) => pair,
            None => return s,
        };
        let exp_val: i32 = match exp.parse() {
            Ok(v) => v,
            Err(_) => return s,
        };
        let sign = if exp_val >= 0 { "+" } else { "" };
        format!("{}e{}{:02}", mant, sign, exp_val.abs())
    } else {
        let s = format!("{}", x);
        if s.contains('.') {
            s
        } else {
            format!("{}.0", s)
        }
    }
}

// ---------------------------------------------------------------------------
// `_clean_exif_value` / `_clean_exif_datetime` / 跳过规则
// ---------------------------------------------------------------------------

/// Python 空白（`str.strip()` + `re \s`）：含 U+001C-U+001F 等控制空白。
fn is_py_whitespace(c: char) -> bool {
    c.is_whitespace() || matches!(c, '\u{001C}'..='\u{001F}')
}

/// `file_info_service._clean_exif_value`（L1011-1021）复刻。
fn clean_exif_value(text: &str) -> Option<String> {
    let text = text.trim_matches(is_py_whitespace);
    if text.is_empty() || text == "None" {
        return None;
    }
    if text.starts_with('[') {
        return None;
    }
    if text.chars().count() > 2000 {
        return None;
    }
    Some(collapse_whitespace(text))
}

/// `re.sub(r"\s+", " ", text)` 复刻（入参已 trim，无首尾空白）。
fn collapse_whitespace(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut pending = false;
    for c in text.chars() {
        if is_py_whitespace(c) {
            pending = true;
        } else {
            if pending {
                out.push(' ');
                pending = false;
            }
            out.push(c);
        }
    }
    if pending {
        out.push(' ');
    }
    out
}

/// `file_info_service._clean_exif_datetime`（L1024-1029）复刻：
/// `YYYY:MM:DD` 前缀 → `YYYY-MM-DD`。
fn clean_exif_datetime(text: &str) -> String {
    let chars: Vec<char> = text.chars().collect();
    let is_digit = |i: usize| chars.get(i).is_some_and(|c| c.is_ascii_digit());
    let ymd_ok = chars.len() >= 10
        && is_digit(0)
        && is_digit(1)
        && is_digit(2)
        && is_digit(3)
        && chars[4] == ':'
        && is_digit(5)
        && is_digit(6)
        && chars[7] == ':'
        && is_digit(8)
        && is_digit(9);
    if !ymd_ok {
        return text.to_string();
    }
    let y: String = chars[0..4].iter().collect();
    let m: String = chars[5..7].iter().collect();
    let d: String = chars[8..10].iter().collect();
    let old: String = chars[0..10].iter().collect();
    text.replacen(&old, &format!("{}-{}-{}", y, m, d), 1)
}

/// 依 exifread 顺序（文件内平铺序）收集 `(common, rest)` 两组行。
fn collect_rows(exif: &Exif) -> (Vec<String>, Vec<String>) {
    let mut common: Vec<String> = Vec::new();
    let mut rest: Vec<String> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for field in exif.fields() {
        // exifread details=False 的 IGNORE_TAGS（任意 IFD 内）。
        if IGNORE_TAG_NUMBERS.contains(&field.tag.number()) {
            continue;
        }
        let key = exifread_key(&field.tag, field.ifd_num.index());
        let key_lower = key.to_lowercase();
        if EXIF_DROP_NAMES.contains(&key_lower.as_str()) || key_lower.starts_with("maker") {
            continue;
        }
        if seen.contains(&key) {
            continue;
        }
        let Some(value) = exifread_printable(&field.tag, &field.value) else {
            continue;
        };
        let Some(value) = clean_exif_value(&value) else {
            continue;
        };
        seen.insert(key.clone());
        if let Some((_, label)) = COMMON_LABELS.iter().find(|(k, _)| *k == key.as_str()) {
            common.push(format!("{}: {}", label, clean_exif_datetime(&value)));
        } else {
            rest.push(format!("{}: {}", key, value));
        }
    }
    (common, rest)
}

/// 解析路径所指图片的 EXIF 为 JSON（`(common, rest)` 两组行）。
///
/// - 成功：`{"common":["label: value",…],"rest":["label: value",…]}`；
/// - 失败：`Err(状态码)`（FFI 侧返回 null），不 panic。损坏/空/缺失/无 EXIF
///   文件均属失败（Python 侧回退 exifread）。
pub fn parse_exif_impl(path: &str) -> Result<serde_json::Value, i32> {
    if path.is_empty() {
        return Err(STATUS_INVALID_ARG);
    }
    let file = match std::fs::File::open(path) {
        Ok(f) => f,
        Err(e) => {
            return Err(if e.kind() == std::io::ErrorKind::NotFound {
                STATUS_NOT_FOUND
            } else {
                STATUS_IO_ERROR
            });
        }
    };
    let mut reader = std::io::BufReader::new(file);
    let mut parser = Reader::new();
    parser.continue_on_error(true);
    let exif = match parser.read_from_container(&mut reader) {
        Ok(exif) => exif,
        Err(ExifError::PartialResult(partial)) => partial.into_inner().0,
        Err(ExifError::Io(e)) => {
            return Err(if e.kind() == std::io::ErrorKind::NotFound {
                STATUS_NOT_FOUND
            } else {
                STATUS_IO_ERROR
            });
        }
        Err(ExifError::NotFound(_)) => return Err(STATUS_NOT_FOUND),
        Err(_) => return Err(STATUS_UNSUPPORTED),
    };
    let (common, rest) = collect_rows(&exif);
    Ok(serde_json::json!({
        "common": common,
        "rest": rest,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    // -------------------------------------------------------------------
    // 小端 TIFF 构造器（供单测生成样本）
    // -------------------------------------------------------------------

    type Entry = (u16, u16, u32, Vec<u8>);

    /// 组装多 IFD 小端 TIFF；返回 `(bytes, 各 IFD 偏移)`。0 号 IFD 偏移恒为 8。
    fn assemble(ifds: &[Vec<Entry>]) -> (Vec<u8>, Vec<u32>) {
        let mut offsets = Vec::new();
        let mut cur = 8u32;
        for ifd in ifds {
            offsets.push(cur);
            cur += 2 + 12 * ifd.len() as u32 + 4;
        }
        let mut body = Vec::new();
        let mut data_cursor = cur as usize;
        let mut out = Vec::new();
        out.extend_from_slice(b"II\x2a\x00");
        out.extend_from_slice(&8u32.to_le_bytes());
        for entries in ifds {
            out.extend_from_slice(&(entries.len() as u16).to_le_bytes());
            for (tag, typ, cnt, val) in entries {
                let mut e = [0u8; 12];
                e[0..2].copy_from_slice(&tag.to_le_bytes());
                e[2..4].copy_from_slice(&typ.to_le_bytes());
                e[4..8].copy_from_slice(&cnt.to_le_bytes());
                if val.len() <= 4 {
                    e[8..8 + val.len()].copy_from_slice(val);
                } else {
                    e[8..12].copy_from_slice(&(data_cursor as u32).to_le_bytes());
                    body.extend_from_slice(val);
                    data_cursor += val.len();
                }
                out.extend_from_slice(&e);
            }
            out.extend_from_slice(&0u32.to_le_bytes());
        }
        out.extend_from_slice(&body);
        (out, offsets)
    }

    fn ascii(s: &str) -> Vec<u8> {
        format!("{}\0", s).into_bytes()
    }

    fn short(v: u16) -> Vec<u8> {
        v.to_le_bytes().to_vec()
    }

    fn shorts(v: &[u16]) -> Vec<u8> {
        v.iter().flat_map(|x| x.to_le_bytes()).collect()
    }

    fn long(v: u32) -> Vec<u8> {
        v.to_le_bytes().to_vec()
    }

    fn rational(n: u32, d: u32) -> Vec<u8> {
        let mut b = n.to_le_bytes().to_vec();
        b.extend_from_slice(&d.to_le_bytes());
        b
    }

    fn undefined(bytes: &[u8]) -> Vec<u8> {
        bytes.to_vec()
    }

    const T_ASCII: u16 = 2;
    const T_SHORT: u16 = 3;
    const T_LONG: u16 = 4;
    const T_RATIONAL: u16 = 5;
    const T_UNDEFINED: u16 = 7;

    static TEMP_COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

    fn write_temp(bytes: &[u8]) -> std::path::PathBuf {
        let n = TEMP_COUNTER.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!(
            "faf_exif_test_{}_{}.tif",
            std::process::id(),
            n
        ));
        std::fs::write(&path, bytes).expect("写临时样本失败");
        path
    }

    fn rows_rest(value: &serde_json::Value) -> Vec<String> {
        value["rest"]
            .as_array()
            .expect("rest 应为数组")
            .iter()
            .map(|v| v.as_str().expect("rest 元素应为字符串").to_string())
            .collect()
    }

    // -------------------------------------------------------------------
    // helper 单测
    // -------------------------------------------------------------------

    #[test]
    fn clean_value_rules() {
        assert_eq!(clean_exif_value("  TestMaker  ").as_deref(), Some("TestMaker"));
        assert_eq!(clean_exif_value("").as_deref(), None);
        assert_eq!(clean_exif_value("   ").as_deref(), None);
        assert_eq!(clean_exif_value("None").as_deref(), None);
        assert_eq!(clean_exif_value("[1/2, 1/2]").as_deref(), None);
        assert_eq!(clean_exif_value("a  \tb\nc").as_deref(), Some("a b c"));
        let long = "x".repeat(2001);
        assert_eq!(clean_exif_value(&long).as_deref(), None);
        assert_eq!(clean_exif_value("2000chars"), Some("2000chars".to_string()));
    }

    #[test]
    fn clean_datetime_rules() {
        assert_eq!(
            clean_exif_datetime("2023:01:15 10:30:00"),
            "2023-01-15 10:30:00"
        );
        assert_eq!(clean_exif_datetime("2023:01:15"), "2023-01-15");
        assert_eq!(clean_exif_datetime("not a date"), "not a date");
        assert_eq!(clean_exif_datetime("20231:01:01x"), "20231:01:01x");
    }

    #[test]
    fn fraction_str_reduces_like_python_fraction() {
        assert_eq!(fraction_str(28, 10), "14/5");
        assert_eq!(fraction_str(1, 250), "1/250");
        assert_eq!(fraction_str(50, 1), "50");
        assert_eq!(fraction_str(72, 1), "72");
        assert_eq!(fraction_str(0, 250), "0");
        assert_eq!(fraction_str(28, 0), "0");
        assert_eq!(fraction_str(0, 0), "0");
        assert_eq!(fraction_str(-2, 4), "-1/2");
        assert_eq!(fraction_str(2, -4), "-1/2");
        assert_eq!(fraction_str(-2, -4), "1/2");
        assert_eq!(fraction_str(4, 4), "1");
    }

    #[test]
    fn make_string_ints_like_python() {
        // ExifVersion "0231" 为 ASCII 字节。
        assert_eq!(make_string_ints(b"0231"), "0231");
        // 全部非打印字符 → join(map(str))；全 0 → 空串。
        assert_eq!(make_string_ints(&[0, 0, 0]), "");
        assert_eq!(make_string_ints(&[0, 1, 0]), "010");
        // 32..256 之外的字节被跳过。
        assert_eq!(make_string_ints(&[65, 0, 66]), "AB");
        // 收尾空白剔除。
        assert_eq!(make_string_ints(&[65, 32, 66, 32]), "A B");
    }

    #[test]
    fn py_bytes_repr_like_python() {
        assert_eq!(py_bytes_repr(b"\xff\x00"), "b'\\xff\\x00'");
        assert_eq!(py_bytes_repr(b"A B"), "b'A B'");
        assert_eq!(py_bytes_repr(b"a\\b'c"), r#"b'a\\b\'c'"#);
        assert_eq!(py_bytes_repr(b"\n\r\t"), "b'\\n\\r\\t'");
        assert_eq!(py_bytes_repr(b"\x7f"), "b'\\x7f'");
    }

    #[test]
    fn exifread_key_prefixes() {
        // Tiff In(0) → Image；In(1) → Thumbnail；In(2) → IFD 2。
        assert_eq!(
            exifread_key(&Tag(Context::Tiff, 0x010F), 0),
            "Image Make"
        );
        assert_eq!(
            exifread_key(&Tag(Context::Tiff, 0x010F), 1),
            "Thumbnail Make"
        );
        assert_eq!(
            exifread_key(&Tag(Context::Tiff, 0x010F), 2),
            "IFD 2 Make"
        );
        assert_eq!(
            exifread_key(&Tag(Context::Exif, 0x9003), 0),
            "EXIF DateTimeOriginal"
        );
        assert_eq!(
            exifread_key(&Tag(Context::Gps, 0x0001), 0),
            "GPS GPSLatitudeRef"
        );
        assert_eq!(
            exifread_key(&Tag(Context::Interop, 0x0002), 0),
            "Interoperability InteroperabilityVersion"
        );
        // 未知标签 → "Tag 0xXXXX"。
        assert_eq!(
            exifread_key(&Tag(Context::Tiff, 0xF0F0), 0),
            "Image Tag 0xF0F0"
        );
        assert_eq!(exifread_key(&Tag(Context::Gps, 0x0020), 0), "GPS Tag 0x0020");
    }

    // -------------------------------------------------------------------
    // parse_exif_impl 单测
    // -------------------------------------------------------------------

    #[test]
    fn normal_file_matches_exifread_semantics() {
        // IFD0（Image）：Make/Model/Orientation/Software/DateTime/XResolution/
        // ResolutionUnit/YCbCrSubSampling/BitsPerSample/ExifOffset（末位）。
        let n0 = 10u32;
        let exif_ifd_off = 8 + 2 + 12 * n0 + 4;
        let (bytes, _offsets) = assemble(&[vec![
            (0x010F, T_ASCII, 10, ascii("TestMaker")),
            (0x0110, T_ASCII, 10, ascii("TestModel")),
            (0x0112, T_SHORT, 1, short(6)),
            (0x0131, T_ASCII, 7, ascii("Pillow")),
            (0x0132, T_ASCII, 20, ascii("2023:01:15 10:30:00")),
            (0x011A, T_RATIONAL, 1, rational(72, 1)),
            (0x0128, T_SHORT, 1, short(2)),
            (0x0212, T_SHORT, 2, shorts(&[2, 2])),
            (0x0102, T_SHORT, 3, shorts(&[8, 8, 8])),
            (0x8769, T_LONG, 1, long(exif_ifd_off)),
        ], vec![
            (0x9003, T_ASCII, 20, ascii("2023:01:15 10:30:00")),
            (0x829D, T_RATIONAL, 1, rational(28, 10)),
            (0x8827, T_SHORT, 1, short(400)),
            (0x920A, T_RATIONAL, 1, rational(50, 1)),
            (0xA001, T_SHORT, 1, short(1)),
            (0x8822, T_SHORT, 1, short(2)),
            (0x9207, T_SHORT, 1, short(5)),
            (0x9209, T_SHORT, 1, short(0)),
            (0x9000, T_UNDEFINED, 4, undefined(b"0231")),
        ]]);
        let path = write_temp(&bytes);
        let value = parse_exif_impl(&path.to_string_lossy()).expect("正常样本应解析成功");
        let rest = rows_rest(&value);
        assert_eq!(
            rest,
            vec![
                "Image Make: TestMaker",
                "Image Model: TestModel",
                "Image Orientation: Rotated 90 CW",
                "Image Software: Pillow",
                "Image DateTime: 2023:01:15 10:30:00",
                "Image XResolution: 72",
                "Image ResolutionUnit: Pixels/Inch",
                // YCbCrSubSampling / BitsPerSample 为列表型 → 丢弃
                "EXIF DateTimeOriginal: 2023:01:15 10:30:00",
                "EXIF FNumber: 14/5",
                "EXIF ISOSpeedRatings: 400",
                "EXIF FocalLength: 50",
                "EXIF ColorSpace: sRGB",
                "EXIF ExposureProgram: Program Normal",
                "EXIF MeteringMode: Pattern",
                "EXIF Flash: Flash did not fire",
                "EXIF ExifVersion: 0231",
            ]
        );
        assert_eq!(value["common"].as_array().map(|a| a.len()), Some(0));
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn gps_and_multi_value_fields() {
        // PIL 平铺布局（与对拍样本一致）：IFD0 = [Make, Model, GPSInfo→IFD1]，
        // IFD1 = GPS 子 IFD。kamadak 仅在 GPSInfo 指针位于 Tiff 上下文
        //（0th/缩略图 IFD）时递归 GPS。
        let n0 = 3u32;
        let gps_ifd_off = 8 + 2 + 12 * n0 + 4;
        let (bytes, _offsets) = assemble(&[
            vec![
                (0x010F, T_ASCII, 10, ascii("TestMaker")),
                (0x0110, T_ASCII, 10, ascii("TestModel")),
                (0x8825, T_LONG, 1, long(gps_ifd_off)),
            ],
            vec![
                (0x0001, T_ASCII, 2, ascii("N")),
                (0x0002, T_RATIONAL, 3, {
                    let mut b = rational(28, 1);
                    b.extend_from_slice(&rational(0, 1));
                    b.extend_from_slice(&rational(0, 1));
                    b
                }),
                (0x0003, T_ASCII, 2, ascii("W")),
                (0x0004, T_RATIONAL, 3, {
                    let mut b = rational(10, 1);
                    b.extend_from_slice(&rational(0, 1));
                    b.extend_from_slice(&rational(0, 1));
                    b
                }),
            ],
        ]);
        let path = write_temp(&bytes);
        let value = parse_exif_impl(&path.to_string_lossy()).expect("GPS 样本应解析成功");
        let rest = rows_rest(&value);
        // GPSLatitude/Longitude 为多值 rational → 列表型 → 丢弃；GPSInfo 指针
        // 被 kamadak 消费 → 不输出（对拍 accepted-diff）。
        assert_eq!(
            rest,
            vec![
                "Image Make: TestMaker",
                "Image Model: TestModel",
                "GPS GPSLatitudeRef: N",
                "GPS GPSLongitudeRef: W",
            ]
        );
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn gps_pointer_in_exif_ifd_is_plain_field() {
        // 真实相机布局：GPSInfo(0x8825) 在 EXIF IFD 内 → kamadak 不递归 GPS，
        // 而是把指针当普通 Long 字段输出（与 exifread 的 "EXIF GPSInfo" 行一致）。
        let n0 = 3u32;
        let ifd1_off = 8 + 2 + 12 * n0 + 4;
        let (bytes, _offsets) = assemble(&[
            vec![
                (0x010F, T_ASCII, 10, ascii("TestMaker")),
                (0x0110, T_ASCII, 10, ascii("TestModel")),
                (0x8769, T_LONG, 1, long(ifd1_off)),
            ],
            vec![
                (0x9003, T_ASCII, 20, ascii("2023:01:15 10:30:00")),
                (0x8825, T_LONG, 1, long(0)), // GPSInfo 指针（指向无效偏移也无妨，仅当字段）
            ],
        ]);
        let path = write_temp(&bytes);
        let value = parse_exif_impl(&path.to_string_lossy()).expect("样本应解析成功");
        let rest = rows_rest(&value);
        assert_eq!(
            rest,
            vec![
                "Image Make: TestMaker",
                "Image Model: TestModel",
                "EXIF DateTimeOriginal: 2023:01:15 10:30:00",
                "EXIF GPSInfo: 0",
            ]
        );
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn corrupt_file_returns_err() {
        let path = write_temp(b"\x00\xff\x01\x02 this is not an image file at all....");
        assert!(parse_exif_impl(&path.to_string_lossy()).is_err());
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn empty_file_returns_err() {
        let path = write_temp(b"");
        assert!(parse_exif_impl(&path.to_string_lossy()).is_err());
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn missing_file_returns_not_found() {
        let path = std::env::temp_dir().join("faf_exif_missing_does_not_exist_42.tif");
        let err = parse_exif_impl(&path.to_string_lossy()).unwrap_err();
        assert_eq!(err, STATUS_NOT_FOUND);
    }

    #[test]
    fn empty_path_returns_invalid_arg() {
        assert_eq!(parse_exif_impl("").unwrap_err(), STATUS_INVALID_ARG);
    }

    #[test]
    fn jpeg_without_exif_returns_not_found() {
        // 无 EXIF 的合法 JPEG（SOI + EOI）：exifread 返回空行，native → Err，
        // todo 7 接线后 Python 回退为空行。
        let jpeg = [0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x04, b'J', b'F', b'I', b'F', 0x00, 0xFF, 0xD9];
        let path = write_temp(&jpeg);
        assert!(parse_exif_impl(&path.to_string_lossy()).is_err());
        let _ = std::fs::remove_file(&path);
    }
}
