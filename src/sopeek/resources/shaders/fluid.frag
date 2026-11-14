#version 450

// 流体背景片元着色器：软 SDF 团块 + 噪声域扭曲 + 9 抽样软模糊 + 主题叠加。
// 该源码经 Qt Shader Baker 编译为 fluid.frag.qsb；顶点着色器见 fluid.vert
// （对应 fluid.vert.qsb）。编译命令（每个文件单独执行一次）：
//   pyside6-qsb --glsl "330" --hlsl "50" -o fluid.vert.qsb fluid.vert
//   pyside6-qsb --glsl "330" --hlsl "50" -o fluid.frag.qsb fluid.frag

layout(location = 0) in vec2 v_uv;
layout(location = 0) out vec4 fragColor;

// std140 布局（QRhi 要求所有 uniform 走 uniform block）：
//   偏移   0: u_resolution_time      xy = 分辨率(像素)，z = 时间(秒)
//   偏移  16: u_noise_offset         xy = 噪声漂移
//   偏移  32: u_overlay_color        rgba = 主题叠加色
//   偏移  48: u_palette[5]           rgb = 调色板
//   偏移 128: u_blob_centers[4]      xy = 团块中心
//   偏移 192: u_blob_radii_colors[4] x = 半径，y = 调色板索引
// 总大小 256 字节，与 _FluidGPUShaderWidget._UNIFORM_BLOCK_SIZE 保持一致。
layout(std140, binding = 0) uniform Params {
    vec4 u_resolution_time;
    vec4 u_noise_offset;
    vec4 u_overlay_color;
    vec4 u_palette[5];
    vec4 u_blob_centers[4];
    vec4 u_blob_radii_colors[4];
};

#define PALETTE_SIZE 5
#define BLOB_COUNT 4

// ── 伪随机与噪声 ────────────────────────────────────────────────────────
// 旧实现：value noise + ``fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453)``。
// 两个固有缺陷会在域扭曲（domain warp）上留下轴对齐的矩形痕迹：
//   1. ``uv * 2.0`` 只有 2×2 个 cell，cell 边界是贯穿半个屏幕的直线；
//      smoothstep 插值在边界处导数为 0，两侧形成一个平台折角（亮度断层）。
//      ``t * 0.12`` 让边界缓慢平移，当它扫过画面中线（t≈25s）时，整块
//      色域看上去就像一块被错误裁切的矩形叠加层。
//   2. sin-hash 在大参数下依赖平台的范围归约，相邻 cell 的哈希相关性增强，
//      进一步把噪声推向低频大块。
// 现在改为 PCG 整数哈希 + 梯度噪声（quintic 权重，边界一阶连续）+ 双 octave
// fbm，从结构上消除规则网格。
uint pcg_hash(uint v)
{
    uint state = v * 747796405u + 2891336453u;
    uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}

float hash21(ivec2 p)
{
    uint h = pcg_hash(uint(p.x) ^ pcg_hash(uint(p.y)));
    // 取低 24 位再归一化：float32 尾数只有 24 位，直接除 2^32-1 会丢失低位。
    return float(h & 0x00FFFFFFu) * (1.0 / 16777215.0);
}

vec2 grad21(ivec2 p)
{
    // 双哈希构造随机梯度，避免每像素 sin/cos。Perlin 的 C1 连续性只依赖
    // quintic 权重在 cell 边界处导数为 0，梯度长度无需归一化。
    vec2 h = vec2(hash21(p), hash21(p + ivec2(57, 113)));
    return h * 2.0 - 1.0;
}

// 梯度噪声：输出 [0,1]
float gnoise(vec2 p)
{
    ivec2 i = ivec2(floor(p));
    vec2 f = fract(p);
    vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);

    float g00 = dot(grad21(i), f);
    float g10 = dot(grad21(i + ivec2(1, 0)), f - vec2(1.0, 0.0));
    float g01 = dot(grad21(i + ivec2(0, 1)), f - vec2(0.0, 1.0));
    float g11 = dot(grad21(i + ivec2(1, 1)), f - vec2(1.0, 1.0));

    float v = mix(mix(g00, g10, u.x), mix(g01, g11, u.x), u.y);
    return clamp(0.5 + 0.85 * v, 0.0, 1.0);
}

// 双 octave fbm：高频层打散低频层的规则 cell 结构。
float fbm21(vec2 p)
{
    return gnoise(p) * 0.68 + gnoise(p * 2.07 + vec2(19.7, 7.3)) * 0.32;
}

// Fully soft gaussian-like blob: no hard inner plateau, long smooth tail.
float soft_blob(vec2 uv, vec2 center, float radius)
{
    float d = length(uv - center);
    float outer = radius * 1.9;
    float t = clamp(d / outer, 0.0, 1.0);
    float s = 1.0 - t * t * (3.0 - 2.0 * t);
    return s * s;
}

// Diagonal base gradient matching the CPU renderer so the canvas is always
// fully covered by palette colors (no dark gaps between blobs).
vec3 base_gradient(vec2 uv)
{
    float t = clamp((uv.x + uv.y) * 0.5, 0.0, 1.0);
    if (t < 0.45) {
        return mix(u_palette[3].rgb, u_palette[0].rgb, t / 0.45);
    }
    return mix(u_palette[0].rgb, u_palette[1].rgb, (t - 0.45) / 0.55);
}

// The base gradient is sampled in unwarped screen space (grad_uv) while blobs
// use the domain-warped blob_uv. Warping rotates/translates coordinates
// outside [0,1]; if the gradient were sampled there, its clamped end-stops
// would paint the out-of-range corner triangles with a flat palette end color
// (visible as light wedges along the edges). soft_blob decays smoothly with
// distance, so out-of-range blob_uv is harmless; the gradient must stay
// anchored to the screen to guarantee full smooth coverage.
vec3 sample_scene(vec2 grad_uv, vec2 blob_uv)
{
    const float opacity[BLOB_COUNT] = float[](0.95, 0.90, 0.85, 0.80);
    vec3 col = base_gradient(grad_uv);

    // Source-over blending keeps colors inside the palette gamut instead of
    // additively blowing out to white where blobs overlap.
    for (int i = 0; i < BLOB_COUNT; ++i) {
        int idx = int(u_blob_radii_colors[i].y);
        vec3 blob_col = u_palette[idx % PALETTE_SIZE].rgb;
        float field = soft_blob(blob_uv, u_blob_centers[i].xy, u_blob_radii_colors[i].x);
        col = mix(col, blob_col, field * opacity[i]);
    }
    return col;
}

void main()
{
    vec2 uv = v_uv;

    // Two-octave domain warp: slow global swirl plus local turbulence for an
    // organic, lava-lamp-like flow. Time coefficients are tuned for a
    // clearly visible drift (the CPU-side state already advances in real
    // seconds, so these scale the on-screen speed directly).
    float t = u_resolution_time.z;
    vec2 noise_offset = u_noise_offset.xy;
    float n1 = fbm21(uv * 3.0 + noise_offset + t * 0.12);
    float n2 = fbm21(uv * 4.5 - noise_offset * 0.7 - t * 0.08);
    float angle = (n1 - 0.5) * 0.9 + t * 0.05;
    mat2 rot = mat2(cos(angle), -sin(angle), sin(angle), cos(angle));
    vec2 centered = (uv - vec2(0.5)) * rot;
    uv = vec2(0.5) + centered;
    uv += vec2(n1 - 0.5, n2 - 0.5) * 0.12;

    // 9-tap soft-blur approximation. The gradient tap stays clamped to the
    // unit square so edge pixels never sample a clamped end-stop wedge; the
    // blob tap follows the warped uv.
    vec2 texel = 1.0 / max(u_resolution_time.xy, vec2(1.0));
    vec3 sum = vec3(0.0);
    float weight = 0.0;
    for (int x = -1; x <= 1; ++x) {
        for (int y = -1; y <= 1; ++y) {
            vec2 offset = vec2(float(x), float(y)) * texel * 2.5;
            sum += sample_scene(clamp(v_uv + offset, 0.0, 1.0), uv + offset);
            weight += 1.0;
        }
    }
    vec3 col = sum / weight;

    // Gentle saturation lift for richer, Apple Music-like tones.
    float luma = dot(col, vec3(0.299, 0.587, 0.114));
    col = clamp(mix(vec3(luma), col, 1.18), 0.0, 1.0);

    // Soft vignette adds depth without crushing the palette.
    float vig = smoothstep(1.15, 0.30, length(v_uv - vec2(0.5)));
    col *= mix(0.86, 1.0, vig);

    // Dark / light translucent overlay.
    col = mix(col, u_overlay_color.rgb, u_overlay_color.a);

    // Tiny screen-space dither hides gradient banding on large soft blobs.
    col += (hash21(ivec2(gl_FragCoord.xy)) - 0.5) * (1.5 / 255.0);

    fragColor = vec4(col, 1.0);
}
