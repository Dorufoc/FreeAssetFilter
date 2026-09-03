// mica_render.h —— Mica GPU 渲染原生库的公共 C ABI。
//
// 设计约束
// --------
// 1. **纯 C ABI**：所有导出函数使用 C 链接与 stdint 定长类型，结构体显式
//    对齐，便于 Python ctypes 直接映射（见
//    ``freeassetfilter/core/native/bridges/mica_render.py``）。
// 2. **不抛异常、不跨模块传所有权**：所有失败通过 ``mica_status`` 返回码报告；
//    像素输出写入调用方提供的缓冲区，库内不分配需调用方释放的内存。
// 3. **无框架依赖**：仅使用 D3D11 / D2D1 / DXGI / WIC 系统组件，不依赖
//    XAML Islands、DirectComposition、Win2D、WinRT。
// 4. **可降级**：任何一步失败都返回明确错误码，由 Python 侧回落到
//    ``freeassetfilter/ui/mica`` 的 numpy CPU 管线，保证功能不中断。
//
// 渲染管线（三段，全部在 GPU 上完成）
// ----------------------------------
//   画布纹理 (BGRA8 + mipmap，整个虚拟桌面)
//        │  PsAnalyze   去明度 + 亮度可靠性门控 -> (a·w, b·w, w) RGBA16F
//        ▼
//   含扩边网格 padW × padH
//        │  PsBlur ×2   归一化加权可分离高斯（水平 + 垂直）
//        ▼
//   含扩边网格 padW × padH
//        │  PsComposite tanh 整形 + 等亮度重建 + 「颜色」混合 + TPDF 抖动
//        ▼
//   网格 gridW × gridH (BGRA8) -> staging -> 调用方 RGB8 缓冲
//
// 画布只在壁纸变化时重建，单次 bake 只跑三段管线，成本与窗口尺寸无关。

#ifndef FAF_MICA_RENDER_H
#define FAF_MICA_RENDER_H

#include <stdint.h>

#if defined(MICA_RENDER_BUILD)
#define MICA_API __declspec(dllexport)
#else
#define MICA_API __declspec(dllimport)
#endif

#ifdef __cplusplus
extern "C" {
#endif

/// ABI 版本号。Python 桥接层必须校验该值与自身预期一致，不一致则拒绝加载。
///
/// v2 新增 ``mica_bake_f32``（float32 RGB 合成输出）；v1 的 ``mica_bake``（uint8）
/// 保持不变。
#define MICA_API_VERSION 2

/// 状态码。0 为成功，其余均为失败且已写入 ``mica_last_error`` 描述。
typedef enum mica_status {
    MICA_OK = 0,
    /// 参数非法（空指针、尺寸 <= 0、缓冲区过小等）
    MICA_ERR_INVALID_ARG = 1,
    /// D3D11 设备创建失败（无兼容适配器 / 驱动缺失）
    MICA_ERR_NO_DEVICE = 2,
    /// 设备丢失（TDR / 显卡驱动重启），需重建上下文
    MICA_ERR_DEVICE_LOST = 3,
    /// 尚未构建画布，无法 bake
    MICA_ERR_NO_SOURCE = 4,
    /// HLSL 编译或着色器创建失败
    MICA_ERR_SHADER = 5,
    /// DXGI 桌面复制超时（桌面无变化时属正常情况）
    MICA_ERR_CAPTURE_TIMEOUT = 6,
    /// DXGI 桌面复制不可用（独占会话已被占用 / 安全桌面 / 无输出）
    MICA_ERR_CAPTURE_UNAVAILABLE = 7,
    /// WIC 解码壁纸文件失败
    MICA_ERR_DECODE = 8,
    /// 显存或系统内存不足
    MICA_ERR_OUT_OF_MEMORY = 9,
    /// 当前系统不支持所需特性
    MICA_ERR_UNSUPPORTED = 10,
    /// 其他内部错误
    MICA_ERR_INTERNAL = 11
} mica_status;

/// 画布来源，对应 ``mica.source`` 的 backend 字符串。
typedef enum mica_backend {
    MICA_BACKEND_NONE = 0,
    /// 由壁纸文件解码 + 摆放构建（首选，与 IDesktopWallpaper 配合）
    MICA_BACKEND_WALLPAPER = 1,
    /// 由 DXGI Desktop Duplication 抓取（动态壁纸 / 解码失败时兜底）
    MICA_BACKEND_DXGI = 2,
    /// 由调用方上传的 CPU 像素构建（Python 既有采集链兜底）
    MICA_BACKEND_MEMORY = 3,
    /// 纯色画布（最终降级）
    MICA_BACKEND_SOLID = 4
} mica_backend;

/// 壁纸摆放方式，与 Shell 的 ``DESKTOP_WALLPAPER_POSITION`` 语义一致。
typedef enum mica_position {
    MICA_POS_CENTER = 0,
    MICA_POS_TILE = 1,
    MICA_POS_STRETCH = 2,
    MICA_POS_FIT = 3,
    MICA_POS_FILL = 4,
    MICA_POS_SPAN = 5
} mica_position;

/// 不透明上下文句柄。
typedef struct mica_context mica_context;

#pragma pack(push, 4)

/// 设备与画布状态快照，用于日志与能力协商。
typedef struct mica_device_info {
    /// 恒为 ``MICA_API_VERSION``
    int32_t api_version;
    /// D3D 特性等级，如 ``0xB000`` 表示 11_0
    int32_t feature_level;
    /// 是否降级到 WARP 软件光栅（1 = 是，性能显著低于硬件）
    int32_t use_warp;
    /// DXGI 桌面复制是否可用（-1 = 尚未探测）
    int32_t dxgi_available;
    /// 当前画布尺寸（像素），未构建时为 0
    int32_t canvas_width;
    int32_t canvas_height;
    /// 画布 mipmap 级数
    int32_t canvas_mips;
    /// 当前画布来源，见 :c:enum:`mica_backend`
    int32_t canvas_backend;
    /// 适配器描述（UTF-8，截断到 127 字节 + NUL）
    char adapter[128];
} mica_device_info;

/// 单个显示器的壁纸摆放描述。
typedef struct mica_monitor_layout {
    /// 显示器矩形（虚拟桌面物理像素）
    int32_t x;
    int32_t y;
    int32_t w;
    int32_t h;
    /// 摆放方式，见 :c:enum:`mica_position`
    int32_t position;
    /// Fit / Center 留边填充色，``0x00RRGGBB``
    uint32_t background_rgb;
    /// 壁纸文件绝对路径（UTF-16）。``NULL`` 或空串表示仅填充背景色。
    const wchar_t* wallpaper;
} mica_monitor_layout;

/// 一次烘焙的完整输入。所有几何量均为**虚拟桌面物理像素**或**网格像素**。
typedef struct mica_bake_params {
    /// 窗口矩形（虚拟桌面物理像素）
    int32_t win_x;
    int32_t win_y;
    int32_t win_w;
    int32_t win_h;
    /// 目标网格尺寸（不含扩边），对应 ``config.bake_grid_size`` 的结果
    int32_t grid_w;
    int32_t grid_h;
    /// 采样扩边宽度（网格像素），对应 ``engine.margin_px``
    int32_t margin;
    /// 是否启用 TPDF 抖动（1 = 启用）
    int32_t dither;
    /// 色度低通标准差（网格像素），对应 ``EngineParams.sigma``
    float sigma;
    /// 色度增益，对应 ``EngineParams.gain``
    float gain;
    /// 色度软上限，对应 ``EngineParams.chroma_cap()``
    float chroma_cap;
    /// 色调不透明度 0..1，对应 ``EngineParams.alpha``
    float alpha;
    /// G1 基色的 Oklab L，对应 ``tint.g1_oklab_l``
    float l_ref;
    /// 亮度可靠性门控下限，对应 ``CHROMA_LUMA_GATE_LO``
    float gate_lo;
    /// 亮度可靠性门控上限，对应 ``CHROMA_LUMA_GATE_HI``
    float gate_hi;
    /// 门控羽化宽度，对应 ``CHROMA_LUMA_GATE_FEATHER``
    float gate_feather;
    /// G1 基色，``0x00RRGGBB``
    uint32_t g1_rgb;
} mica_bake_params;

/// 一次烘焙的输出元数据。
typedef struct mica_bake_result {
    /// 实际输出的网格尺寸
    int32_t width;
    int32_t height;
    /// 含扩边的中间纹理尺寸
    int32_t pad_width;
    int32_t pad_height;
    /// 实际采样的虚拟桌面矩形，对应 ``engine.sample_rect_for``
    float sample_x;
    float sample_y;
    float sample_w;
    float sample_h;
    /// GPU 提交 + 回读的墙钟耗时（毫秒）
    float duration_ms;
    /// 画布来源，见 :c:enum:`mica_backend`
    int32_t backend;
} mica_bake_result;

#pragma pack(pop)

// ---------------------------------------------------------------------------
// 生命周期
// ---------------------------------------------------------------------------

/// 创建渲染上下文（含 D3D11 设备、D2D 工厂、WIC 工厂与三段着色器）。
///
/// @param allow_warp  硬件适配器不可用时是否允许降级到 WARP 软件光栅。
/// @param out_ctx     成功时写入新句柄；失败时写入 ``NULL``。
/// @return ``MICA_OK`` 或错误码。
MICA_API mica_status mica_create(int32_t allow_warp, mica_context** out_ctx);

/// 销毁上下文并释放全部 GPU 资源。传入 ``NULL`` 是安全的空操作。
MICA_API void mica_destroy(mica_context* ctx);

/// 读取设备与画布状态。
MICA_API mica_status mica_get_device_info(mica_context* ctx, mica_device_info* out_info);

/// 返回最近一次失败的描述（UTF-8，上下文内静态存储，下次调用即失效）。
/// 从不返回 ``NULL``。
MICA_API const char* mica_last_error(mica_context* ctx);

/// 返回编译期 ABI 版本，用于桥接层在创建上下文前做版本校验。
MICA_API int32_t mica_api_version(void);

// ---------------------------------------------------------------------------
// 画布构建
// ---------------------------------------------------------------------------

/// 声明虚拟桌面几何与画布分辨率上限。必须在任何画布构建之前调用。
///
/// 画布按长边不超过 ``max_long_side`` 等比缩小，缩放系数即 ``canvas_scale``
/// （画布像素 / 虚拟桌面像素），与 ``mica.source._canvas_scale`` 一致。
///
/// @param vx,vy,vw,vh    虚拟桌面矩形（物理像素）。
/// @param max_long_side  画布长边上限，建议 1600。
MICA_API mica_status mica_set_virtual_desktop(mica_context* ctx,
                                             int32_t vx,
                                             int32_t vy,
                                             int32_t vw,
                                             int32_t vh,
                                             int32_t max_long_side);

/// 由壁纸文件构建画布：WIC 解码 -> Direct2D 按 position 摆放到各显示器区域。
///
/// 支持每显示器不同壁纸与不同摆放方式。``MICA_POS_SPAN`` 会让该显示器的壁纸
/// 跨越整个虚拟桌面绘制（与 Windows 的"跨区"语义一致）。
///
/// @param layouts       每显示器一条，长度 ``count``。
/// @param count         显示器数量，必须 >= 1。
/// @param fallback_rgb  未被任何显示器覆盖的画布区域的填充色 ``0x00RRGGBB``。
MICA_API mica_status mica_build_canvas_from_wallpapers(mica_context* ctx,
                                                      const mica_monitor_layout* layouts,
                                                      int32_t count,
                                                      uint32_t fallback_rgb);

/// 由 DXGI Desktop Duplication 抓取当前桌面构建画布。
///
/// 适用于动态壁纸、幻灯片放映、或壁纸文件无法解码的场景。抓取到的帧包含桌面
/// 上的窗口内容，因此只应在**壁纸变化检测**触发时使用，不宜高频调用。
///
/// @param timeout_ms  单个输出的等待上限，建议 120。桌面无变化时会返回
///                    ``MICA_ERR_CAPTURE_TIMEOUT``，调用方应保留旧画布。
MICA_API mica_status mica_build_canvas_from_dxgi(mica_context* ctx, int32_t timeout_ms);

/// 由调用方提供的 CPU 像素构建画布（Python 既有采集链的兜底通道）。
///
/// @param rgb     紧密或带跨距的 RGB8 缓冲，行主序，顶行在前。
/// @param width   像素宽。
/// @param height  像素高。
/// @param stride  行跨距（字节）；传 0 表示 ``width * 3``。
MICA_API mica_status mica_build_canvas_from_memory(mica_context* ctx,
                                                   const uint8_t* rgb,
                                                   int32_t width,
                                                   int32_t height,
                                                   int32_t stride);

/// 构建纯色画布（最终降级路径）。
MICA_API mica_status mica_build_canvas_solid(mica_context* ctx, uint32_t rgb);

/// 探测 DXGI 桌面复制可用性（会真实打开一次复制会话后立即关闭）。
MICA_API mica_status mica_dxgi_probe(mica_context* ctx, int32_t* out_available);

/// 读取当前画布的平均色 ``0x00RRGGBB``，用于纯色降级与自动化校验。
MICA_API mica_status mica_canvas_mean_rgb(mica_context* ctx, uint32_t* out_rgb);

// ---------------------------------------------------------------------------
// 烘焙
// ---------------------------------------------------------------------------

/// 执行一次完整烘焙，输出紧密排列的 RGB8 网格图。
///
/// @param params        输入参数，不可为 ``NULL``。
/// @param out_rgb       输出缓冲，容量需 >= ``grid_w * grid_h * 3``。
/// @param out_capacity  ``out_rgb`` 的字节容量。
/// @param out_result    可为 ``NULL``；非空时写入输出元数据。
MICA_API mica_status mica_bake(mica_context* ctx,
                              const mica_bake_params* params,
                              uint8_t* out_rgb,
                              int32_t out_capacity,
                              mica_bake_result* out_result);

/// 执行一次完整烘焙，输出紧密排列的 float32 RGB 网格图。
///
/// 与 :c:func:`mica_bake` 走完全相同的 Analyze→Blur→Composite 管线与几何
/// （相同的采样矩形 / 扩边 / σ / gain / chroma_cap / alpha / l_ref / 门控），但把
/// 合成结果渲染到 ``R32G32B32A32_FLOAT`` 目标纹理再回读，**不**做 8-bit 量化：
///
/// * 输出的每个像素是 0..1 sRGB 的 ``float``（3 个分量 RGB，行主序），由调用方
///   在显示分辨率上自行量化/抖动，因此本函数**强制关闭**着色器内的 TPDF 抖动。
/// * 单位：``out_capacity`` 以**字节**计，必须 >= ``grid_w * grid_h * 3 * sizeof(float)``。
///
/// @param params        输入参数，不可为 ``NULL``。
/// @param out_rgb       输出缓冲，容量需 >= ``grid_w * grid_h * 3 * sizeof(float)``。
/// @param out_capacity  ``out_rgb`` 的字节容量。
/// @param out_result    可为 ``NULL``；非空时写入输出元数据（与 ``mica_bake`` 一致）。
MICA_API mica_status mica_bake_f32(mica_context* ctx,
                                   const mica_bake_params* params,
                                   float* out_rgb,
                                   int32_t out_capacity,
                                   mica_bake_result* out_result);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // FAF_MICA_RENDER_H
