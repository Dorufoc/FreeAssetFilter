// mica_shaders.h —— Mica GPU 渲染管线的 HLSL 着色器源（内嵌为原始字符串）。
//
// 本文件是 ``freeassetfilter/ui/mica/tint.py`` 的 **逐步 GPU 移植**：每个函数
// 都与 numpy 参考实现一一对应，常数取值也严格一致。任何一侧修改都必须同步
// 另一侧，否则 GPU/CPU 两条路径会产生可见色差。
//
// 对应关系
// --------
//   SrgbToLinear        <-> tint.linear_from_srgb_u8   (sRGB EOTF)
//   LinearToSrgb        <-> tint.srgb_from_linear      (sRGB OETF)
//   LinearToOklab       <-> tint.oklab_from_linear_rgb
//   OklabToLinearRaw    <-> tint._linear_rgb_from_lab_raw
//   OklabToLinear       <-> tint.linear_rgb_from_oklab (色度二分色域映射)
//   LumaPS/ClipColor/SetLum <-> tint.luma_ps/clip_color/set_lum (PDF 规范)
//   PsAnalyze           <-> tint.chroma_from_srgb + tint.chroma_reliability
//   PsBlur              <-> tint.blur_chroma           (归一化加权高斯)
//   PsComposite         <-> tint.shape_chroma + rebuild_source_layer
//                           + compose_tint_float + quantize_u8
//
// 与 CPU 版的**有意差异**（均为质量提升，不改变观感取向）：
//   * 高斯低通在完整网格分辨率上做真高斯，不走 CPU 版的 `_auto_downscale`
//     盒式预降采样近似（CPU 版自述误差约 0.3%）。
//   * 壁纸取样用硬件 mipmap 三线性过滤替代 CPU 版的盒式重采样，抗锯齿更优。
//   * 抖动改用逐像素整数哈希（无需上传贴图），同样跨重绘稳定不闪烁。

#pragma once

// ---------------------------------------------------------------------------
// 公共色彩科学内核
// ---------------------------------------------------------------------------

static const char* const kMicaShaderCommon = R"HLSL(

#define MICA_EPS 1e-6f
// 色域映射二分迭代次数，对应 tint.GAMUT_MAP_ITERS = 12（约 1/4096 精度）。
#define MICA_GAMUT_ITERS 12

Texture2D    gTex : register(t0);
SamplerState gSmp : register(s0);

struct VsOut
{
    float4 pos : SV_Position;
    float2 uv  : TEXCOORD0;
};

// 全屏三角形：由 SV_VertexID 直接生成，无需顶点缓冲。
VsOut VsFullscreen(uint vid : SV_VertexID)
{
    // (-1,-1) (3,-1) (-1,3) 覆盖整个裁剪空间的大三角形
    float2 p = float2((vid == 1) ? 3.0f : -1.0f, (vid == 2) ? 3.0f : -1.0f);
    VsOut o;
    o.pos = float4(p, 0.0f, 1.0f);
    // 裁剪空间 -> UV（y 翻转）
    o.uv = float2((p.x + 1.0f) * 0.5f, (1.0f - p.y) * 0.5f);
    return o;
}

// sRGB 编码值 -> 线性光（分段函数，与 tint.srgb_to_linear_lut 同式）
float3 SrgbToLinear(float3 c)
{
    float3 lo = c / 12.92f;
    float3 hi = pow(max((c + 0.055f) / 1.055f, MICA_EPS), 2.4f);
    return float3(c.r <= 0.04045f ? lo.r : hi.r,
                  c.g <= 0.04045f ? lo.g : hi.g,
                  c.b <= 0.04045f ? lo.b : hi.b);
}

// 线性光 -> sRGB 编码值（允许越界，由调用方裁剪）
float3 LinearToSrgb(float3 c)
{
    c = max(c, 0.0f);
    float3 lo = c * 12.92f;
    float3 hi = 1.055f * pow(max(c, MICA_EPS), 1.0f / 2.4f) - 0.055f;
    return float3(c.r <= 0.0031308f ? lo.r : hi.r,
                  c.g <= 0.0031308f ? lo.g : hi.g,
                  c.b <= 0.0031308f ? lo.b : hi.b);
}

// 线性 sRGB -> Oklab（Bjorn Ottosson, 2020）
float3 LinearToOklab(float3 lin)
{
    float3 lms;
    lms.x = 0.4122214708f * lin.r + 0.5363325363f * lin.g + 0.0514459929f * lin.b;
    lms.y = 0.2119034982f * lin.r + 0.6806995451f * lin.g + 0.1073969566f * lin.b;
    lms.z = 0.0883024619f * lin.r + 0.2817188376f * lin.g + 0.6299787005f * lin.b;
    lms = pow(max(lms, 0.0f), 1.0f / 3.0f);
    return float3(
        0.2104542553f * lms.x + 0.7936177850f * lms.y - 0.0040720468f * lms.z,
        1.9779984951f * lms.x - 2.4285922050f * lms.y + 0.4505937099f * lms.z,
        0.0259040371f * lms.x + 0.7827717662f * lms.y - 0.8086757660f * lms.z);
}

// Oklab -> 线性 sRGB（不做色域映射，允许越界）
float3 OklabToLinearRaw(float3 lab)
{
    float3 m;
    m.x = lab.x + 0.3963377774f * lab.y + 0.2158037573f * lab.z;
    m.y = lab.x - 0.1055613458f * lab.y - 0.0638541728f * lab.z;
    m.z = lab.x - 0.0894841775f * lab.y - 1.2914855480f * lab.z;
    m = m * m * m;
    return float3(
         4.0767416621f * m.x - 3.3077115913f * m.y + 0.2309699292f * m.z,
        -1.2684380046f * m.x + 2.6097574011f * m.y - 0.3413193965f * m.z,
        -0.0041960863f * m.x - 0.7034186147f * m.y + 1.7076147010f * m.z);
}

bool InGamut(float3 rgb)
{
    return all(rgb >= -MICA_EPS) && all(rgb <= 1.0f + MICA_EPS);
}

// Oklab -> 线性 sRGB，越界像素按**色度**二分收缩回色域。
// 保持 L 与色相角不变，只降低彩度，避免"削顶偏色"（亮蓝被削成青）。
float3 OklabToLinear(float3 lab)
{
    float3 rgb = OklabToLinearRaw(lab);
    if (InGamut(rgb))
    {
        return saturate(rgb);
    }
    float lo = 0.0f;
    float hi = 1.0f;
    [unroll]
    for (int i = 0; i < MICA_GAMUT_ITERS; ++i)
    {
        float mid = 0.5f * (lo + hi);
        float3 t = OklabToLinearRaw(float3(lab.x, lab.y * mid, lab.z * mid));
        bool ok = InGamut(t);
        lo = ok ? mid : lo;
        hi = ok ? hi : mid;
    }
    return saturate(OklabToLinearRaw(float3(lab.x, lab.y * lo, lab.z * lo)));
}

// --- PDF 规范「颜色」混合模式的三个辅助函数 -------------------------------
// 注意：亮度定义在**伽马编码后**的 sRGB 分量上（Rec.601 权重），这正是
// Photoshop / PDF 的 Hue/Saturation/Color/Luminosity 所用定义，不可换成
// Rec.709 线性亮度。

float LumaPS(float3 c)
{
    return 0.3f * c.r + 0.59f * c.g + 0.11f * c.b;
}

// 把越界颜色拉回 [0,1] 且严格保持 LumaPS 与色相
float3 ClipColor(float3 c)
{
    float l = LumaPS(c);
    float n = min(min(c.r, c.g), c.b);
    if (n < 0.0f)
    {
        c = l + (c - l) * (l / max(l - n, MICA_EPS));
    }
    float x = max(max(c.r, c.g), c.b);
    if (x > 1.0f)
    {
        c = l + (c - l) * ((1.0f - l) / max(x - l, MICA_EPS));
    }
    return c;
}

// 把颜色 c 的亮度改为 l，保持色相与彩度
float3 SetLum(float3 c, float l)
{
    return ClipColor(c + (l - LumaPS(c)));
}

// 「颜色」混合：结果取下层亮度 + 上层色相/饱和度
float3 ColorBlend(float3 backdrop, float3 source)
{
    return SetLum(source, LumaPS(backdrop));
}

// 逐像素整数哈希（0..1），用于生成确定性抖动噪声。
float Hash21(uint2 p, uint salt)
{
    uint n = p.x * 374761393u + p.y * 668265263u + salt * 1274126177u;
    n = (n ^ (n >> 13u)) * 1274126177u;
    n = n ^ (n >> 16u);
    return float(n & 0x00FFFFFFu) / 16777216.0f;
}

)HLSL";

// ---------------------------------------------------------------------------
// 阶段 A：分析 —— 去明度 + 亮度可靠性门控
// ---------------------------------------------------------------------------
//
// 输入：虚拟桌面画布纹理（sRGB 编码 BGRA + mipmap）
// 输出：R16G16B16A16_FLOAT (a*w, b*w, w, 1)，尺寸 = 含扩边网格 padW x padH
//
// 对应 tint.chroma_from_srgb + tint.chroma_reliability。
// 压暗的暗部与过曝的高光几乎不含可靠色度（只有噪声），若不加权参与低通会把
// 整幅色调拉灰，故用 smoothstep 软门控赋权。

static const char* const kMicaShaderAnalyze = R"HLSL(

cbuffer AnalyzeCB : register(b0)
{
    // 采样矩形（虚拟桌面物理像素，可越界，由采样器钳制）
    float4 gSrcRect;    // x, y, w, h
    // 画布几何：canvasW, canvasH, 画布相对虚拟桌面的缩放, mip 级别
    float4 gCanvas;     // w, h, scale, lodBias
    // 虚拟桌面原点
    float4 gVirtualOrg; // vx, vy, 0, 0
    // 亮度门控参数
    float4 gGate;       // lo, hi, feather, 0
};

float4 PsAnalyze(VsOut i) : SV_Target
{
    // UV -> 采样矩形内的虚拟桌面坐标
    float2 vpos = gSrcRect.xy + i.uv * gSrcRect.zw;
    // 虚拟桌面坐标 -> 画布像素 -> 画布 UV
    float2 cpx = (vpos - gVirtualOrg.xy) * gCanvas.z;
    float2 cuv = cpx / gCanvas.xy;

    // 每个输出像素覆盖的画布像素数 -> mip 级别，硬件三线性抗锯齿。
    // 这替代了 CPU 版的盒式重采样，等价且质量更好。
    float3 srgb = gTex.SampleLevel(gSmp, cuv, gCanvas.w).rgb;

    float3 lin = SrgbToLinear(srgb);
    float3 lab = LinearToOklab(lin);

    // Rec.709 线性亮度，仅作门控权重，不参与合成
    float y = dot(lin, float3(0.2126f, 0.7152f, 0.0722f));

    float feather = max(gGate.z, MICA_EPS);
    float wlo = saturate((y - gGate.x) / feather);
    float whi = saturate((gGate.y - y) / feather);
    float t = min(wlo, whi);
    float w = t * t * (3.0f - 2.0f * t);   // smoothstep

    return float4(lab.y * w, lab.z * w, w, 1.0f);
}

)HLSL";

// ---------------------------------------------------------------------------
// 阶段 B：归一化加权可分离高斯低通
// ---------------------------------------------------------------------------
//
// 数学形式（逐通道）：  a_bar = (G_s * (w*a)) / (G_s * w)
// 三个平面 (w*a, w*b, w) 共享同一个核，一次卷完；分母归一化保证"只做加权
// 平均、不改变色度总量"。只在 (a,b) 平面卷积，明度不参与，因此绝不会产生
// 明暗光晕。边缘用采样器 CLAMP 实现钳制填充。
//
// 对应 tint.blur_chroma（但不做预降采样，直接真高斯）。

static const char* const kMicaShaderBlur = R"HLSL(

cbuffer BlurCB : register(b0)
{
    // texel 步进方向：水平 pass = (1/w, 0)，垂直 pass = (0, 1/h)
    float4 gStep;       // dx, dy, 0, 0
    // sigma、半径、归一化系数
    float4 gKernel;     // sigma, radius, invTwoSigmaSq, 0
};

float4 PsBlur(VsOut i) : SV_Target
{
    int radius = (int)gKernel.y;
    if (radius <= 0)
    {
        return gTex.SampleLevel(gSmp, i.uv, 0.0f);
    }

    // 中心权重 1.0（exp(0)），先累加中心项
    float3 acc = gTex.SampleLevel(gSmp, i.uv, 0.0f).rgb;
    float wsum = 1.0f;

    // 对称累加，循环次数减半
    for (int k = 1; k <= radius; ++k)
    {
        float fk = (float)k;
        float wk = exp(-(fk * fk) * gKernel.z);
        float2 off = gStep.xy * fk;
        acc += wk * gTex.SampleLevel(gSmp, i.uv + off, 0.0f).rgb;
        acc += wk * gTex.SampleLevel(gSmp, i.uv - off, 0.0f).rgb;
        wsum += 2.0f * wk;
    }

    return float4(acc / wsum, 1.0f);
}

)HLSL";

// ---------------------------------------------------------------------------
// 阶段 C：合成 —— 色度整形 + 等亮度重建 + 「颜色」混合 + 抖动量化
// ---------------------------------------------------------------------------
//
// 输入：模糊后的 (num_a, num_b, den)，含扩边
// 输出：B8G8R8A8_UNORM，尺寸 = 网格 gridW x gridH（裁掉扩边）
//
// 对应 tint.shape_chroma -> rebuild_source_layer -> compose_tint_float
//      -> quantize_u8。

static const char* const kMicaShaderComposite = R"HLSL(

cbuffer CompositeCB : register(b0)
{
    // gain, chromaCap, alpha, lRef(G1 的 Oklab L)
    float4 gShape;
    // G1 基色（sRGB 编码 0..1）+ 抖动开关
    float4 gBase;       // r, g, b, ditherEnabled
    // 扩边与含扩边尺寸，用于把网格 UV 映射到 interior
    float4 gGeom;       // margin, padW, padH, 0
};

float4 PsComposite(VsOut i) : SV_Target
{
    // 网格像素 -> 含扩边纹理 UV（裁出 interior）
    float2 gridPx = i.uv * float2(gGeom.y - 2.0f * gGeom.x,
                                  gGeom.z - 2.0f * gGeom.x);
    float2 uv = (gGeom.x + gridPx) / gGeom.yz;

    float3 s = gTex.SampleLevel(gSmp, uv, 0.0f).rgb;

    // 归一化加权低通的除法收尾
    float den = max(s.z, MICA_EPS);
    float2 ab = s.xy / den;

    // 色度整形：增益 + tanh 软限幅（逐像素独立，色相角严格不变）
    float cap = max(gShape.y, MICA_EPS);
    float c = length(ab);
    float cOut = cap * tanh((c * gShape.x) / cap);
    ab *= cOut / max(c, MICA_EPS);

    // 等亮度重建：所有像素共享同一个 Oklab L，明暗结构被彻底抹除
    float3 srcSrgb = LinearToSrgb(OklabToLinear(float3(gShape.w, ab.x, ab.y)));

    // 「颜色」混合到 G1 之上，再按 alpha 线性控制色调强度
    float3 g1 = gBase.rgb;
    float3 tinted = ColorBlend(g1, srcSrgb);
    float3 outc = g1 + (tinted - g1) * gShape.z;

    // TPDF 抖动：消除 8-bit 大面积渐变的色带。种子只依赖像素坐标，
    // 因此跨重绘完全稳定，不会闪烁。
    if (gBase.w > 0.5f)
    {
        uint2 p = (uint2)i.pos.xy;
        float d = (Hash21(p, 42u) - Hash21(p, 1337u)) * 0.5f;
        outc += d / 255.0f;
    }

    return float4(saturate(outc), 1.0f);
}

)HLSL";
