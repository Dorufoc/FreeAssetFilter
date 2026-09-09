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

float hash(vec2 p)
{
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float noise(vec2 p)
{
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);

    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));

    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
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
    float n1 = noise(uv * 2.0 + noise_offset + t * 0.12);
    float n2 = noise(uv * 3.5 - noise_offset * 0.7 - t * 0.08);
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
    col += (hash(gl_FragCoord.xy) - 0.5) * (1.5 / 255.0);

    fragColor = vec4(col, 1.0);
}
