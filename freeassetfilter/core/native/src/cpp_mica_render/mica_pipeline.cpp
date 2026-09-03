// mica_pipeline.cpp —— 三段 GPU 管线编排与像素回读。
//
// 数据流
// ------
//   canvas(mip 链, BGRA8)
//        │ PsAnalyze                       视口 padW x padH
//        ▼ stageA (RGBA16F: a·w, b·w, w)
//        │ PsBlur 水平
//        ▼ stageB
//        │ PsBlur 垂直
//        ▼ stageA
//        │ PsComposite                     视口 gridW x gridH
//        ▼ outTex (BGRA8)
//        │ CopyResource
//        ▼ readback (STAGING) -> Map -> 调用方 RGB8
//
// 坐标对齐
// --------
// CPU 参考实现 ``resample._sample_coords`` 的映射是
// ``t = (i + 0.5)·span/n + origin - 0.5``（纹素索引空间）；GPU 采样器的
// UV ``u`` 对应纹素索引 ``u·W - 0.5``。两式联立得 ``u = (origin + (i+0.5)·
// span/n) / W``，正是着色器中 ``cuv = cpx / canvasSize`` 的形式——因此**无需**
// 额外的半纹素偏移，两条路径逐像素对齐。
//
// 中间纹理精度
// ------------
// 分析与模糊阶段用 R16G16B16A16_FLOAT。Oklab 的 a/b 量级约 ±0.4，半精度在该
// 区间的相对误差约 5e-4，远小于最终 8-bit 量化步长（1/255 ≈ 3.9e-3），故不会
// 引入可见误差；相比 32F 可省一半带宽。

#include "mica_internal.h"

#include <algorithm>

namespace mica {

namespace {

/// 中间纹理格式：见文件头"中间纹理精度"说明。
constexpr DXGI_FORMAT kFieldFormat = DXGI_FORMAT_R16G16B16A16_FLOAT;

/// 以 WRITE_DISCARD 更新动态常量缓冲。
bool UploadCb(Context* c, ID3D11Buffer* buffer, const void* data, size_t size) {
    D3D11_MAPPED_SUBRESOURCE mapped = {};
    if (FAILED(c->ctx->Map(buffer, 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped))) {
        return false;
    }
    ::memcpy(mapped.pData, data, size);
    c->ctx->Unmap(buffer, 0);
    return true;
}

/// 执行一次全屏 pass。
void DrawPass(Context* c,
              ID3D11PixelShader* ps,
              ID3D11ShaderResourceView* srv,
              ID3D11Buffer* cb,
              ID3D11RenderTargetView* rtv,
              int w,
              int h) {
    ID3D11DeviceContext* dc = c->ctx.Get();
    UnbindAll(c);
    SetTarget(c, rtv, w, h);
    dc->PSSetShader(ps, nullptr, 0);
    ID3D11ShaderResourceView* srvs[] = {srv};
    dc->PSSetShaderResources(0, 1, srvs);
    ID3D11Buffer* cbs[] = {cb};
    dc->PSSetConstantBuffers(0, 1, cbs);
    dc->Draw(3, 0);
}

/// 高精度墙钟计时（毫秒）。
double NowMs() {
    static LARGE_INTEGER freq = {};
    if (freq.QuadPart == 0) {
        ::QueryPerformanceFrequency(&freq);
    }
    LARGE_INTEGER now = {};
    ::QueryPerformanceCounter(&now);
    if (freq.QuadPart == 0) {
        return 0.0;
    }
    return (static_cast<double>(now.QuadPart) * 1000.0) / static_cast<double>(freq.QuadPart);
}

}  // namespace

mica_status RunBake(Context* c,
                    const mica_bake_params* p,
                    uint8_t* outRgb,
                    int capacity,
                    mica_bake_result* outResult) {
    if (p == nullptr || outRgb == nullptr) {
        return Fail(c, MICA_ERR_INVALID_ARG, "params 或 out_rgb 为空");
    }
    if (!c->canvas || c->canvasBackend == MICA_BACKEND_NONE) {
        return Fail(c, MICA_ERR_NO_SOURCE, "尚未构建画布");
    }

    const int gridW = Clamp(p->grid_w, 1, kMaxPadSide);
    const int gridH = Clamp(p->grid_h, 1, kMaxPadSide);
    const int needed = gridW * gridH * 3;
    if (capacity < needed) {
        return Fail(c, MICA_ERR_INVALID_ARG, "输出缓冲过小：需要 %d 字节，实际 %d", needed,
                    capacity);
    }

    // 扩边受 pad 上限约束，保证中间纹理尺寸可控。
    const int maxMargin = (kMaxPadSide - (std::max)(gridW, gridH)) / 2;
    const int margin = Clamp(p->margin, 0, (std::max)(0, maxMargin));
    const int padW = gridW + 2 * margin;
    const int padH = gridH + 2 * margin;

    const double t0 = NowMs();

    mica_status st = EnsureRenderTexture(c, &c->stageA, padW, padH, kFieldFormat);
    if (st != MICA_OK) {
        return st;
    }
    st = EnsureRenderTexture(c, &c->stageB, padW, padH, kFieldFormat);
    if (st != MICA_OK) {
        return st;
    }
    st = EnsureRenderTexture(c, &c->outTex, gridW, gridH, DXGI_FORMAT_B8G8R8A8_UNORM);
    if (st != MICA_OK) {
        return st;
    }
    st = EnsureReadback(c, gridW, gridH);
    if (st != MICA_OK) {
        return st;
    }

    // --- 采样矩形：对齐 engine.sample_rect_for -----------------------------
    const float winW = (std::max)(1.0f, static_cast<float>(p->win_w));
    const float winH = (std::max)(1.0f, static_cast<float>(p->win_h));
    const float densityX = static_cast<float>(gridW) / winW;
    const float densityY = static_cast<float>(gridH) / winH;
    const float mx = static_cast<float>(margin) / (std::max)(densityX, 1e-6f);
    const float my = static_cast<float>(margin) / (std::max)(densityY, 1e-6f);
    const float rectX = static_cast<float>(p->win_x) - mx;
    const float rectY = static_cast<float>(p->win_y) - my;
    const float rectW = winW + 2.0f * mx;
    const float rectH = winH + 2.0f * my;

    BindFullscreenState(c);

    // --- 阶段 A：分析 ------------------------------------------------------
    // LOD 取两轴中较大的降采样倍率，避免高频壁纸在长边方向出现走样。
    const float spanCanvasX = rectW * c->canvasScale;
    const float spanCanvasY = rectH * c->canvasScale;
    const float ratio = (std::max)(spanCanvasX / static_cast<float>(padW),
                                   spanCanvasY / static_cast<float>(padH));
    const float lod = (ratio > 1.0f) ? ::log2f(ratio) : 0.0f;

    AnalyzeCB acb = {};
    acb.srcRect[0] = rectX;
    acb.srcRect[1] = rectY;
    acb.srcRect[2] = rectW;
    acb.srcRect[3] = rectH;
    acb.canvas[0] = static_cast<float>(c->canvasW);
    acb.canvas[1] = static_cast<float>(c->canvasH);
    acb.canvas[2] = c->canvasScale;
    acb.canvas[3] = Clamp(lod, 0.0f, static_cast<float>((std::max)(c->canvasMips - 1, 0)));
    acb.virtualOrg[0] = static_cast<float>(c->vx);
    acb.virtualOrg[1] = static_cast<float>(c->vy);
    acb.gate[0] = p->gate_lo;
    acb.gate[1] = p->gate_hi;
    acb.gate[2] = (std::max)(p->gate_feather, 1e-6f);
    if (!UploadCb(c, c->cbAnalyze.Get(), &acb, sizeof(acb))) {
        return Fail(c, MICA_ERR_DEVICE_LOST, "更新 AnalyzeCB 失败（设备可能已丢失）");
    }
    DrawPass(c, c->psAnalyze.Get(), c->canvasSrv.Get(), c->cbAnalyze.Get(), c->stageA.rtv.Get(),
             padW, padH);

    // --- 阶段 B：归一化加权可分离高斯 -------------------------------------
    const float sigma = (std::max)(p->sigma, 0.0f);
    int radius = static_cast<int>(::ceilf(kGaussianRadiusSigmas * (std::max)(sigma, 1e-6f)));
    radius = Clamp(radius, 1, kMaxBlurRadius);

    BlurCB bcb = {};
    bcb.kernel[0] = sigma;
    bcb.kernel[1] = static_cast<float>(radius);
    bcb.kernel[2] = 1.0f / (2.0f * (std::max)(sigma, 1e-6f) * (std::max)(sigma, 1e-6f));

    if (sigma > 1e-4f) {
        // 水平：stageA -> stageB
        bcb.step[0] = 1.0f / static_cast<float>(padW);
        bcb.step[1] = 0.0f;
        if (!UploadCb(c, c->cbBlur.Get(), &bcb, sizeof(bcb))) {
            return Fail(c, MICA_ERR_DEVICE_LOST, "更新 BlurCB(H) 失败");
        }
        DrawPass(c, c->psBlur.Get(), c->stageA.srv.Get(), c->cbBlur.Get(), c->stageB.rtv.Get(),
                 padW, padH);

        // 垂直：stageB -> stageA
        bcb.step[0] = 0.0f;
        bcb.step[1] = 1.0f / static_cast<float>(padH);
        if (!UploadCb(c, c->cbBlur.Get(), &bcb, sizeof(bcb))) {
            return Fail(c, MICA_ERR_DEVICE_LOST, "更新 BlurCB(V) 失败");
        }
        DrawPass(c, c->psBlur.Get(), c->stageB.srv.Get(), c->cbBlur.Get(), c->stageA.rtv.Get(),
                 padW, padH);
    }

    // --- 阶段 C：合成 -----------------------------------------------------
    float g1[3];
    UnpackRgb(p->g1_rgb, g1);
    CompositeCB ccb = {};
    ccb.shape[0] = p->gain;
    ccb.shape[1] = (std::max)(p->chroma_cap, 1e-6f);
    ccb.shape[2] = Clamp(p->alpha, 0.0f, 1.0f);
    ccb.shape[3] = p->l_ref;
    ccb.base[0] = g1[0];
    ccb.base[1] = g1[1];
    ccb.base[2] = g1[2];
    ccb.base[3] = (p->dither != 0) ? 1.0f : 0.0f;
    ccb.geom[0] = static_cast<float>(margin);
    ccb.geom[1] = static_cast<float>(padW);
    ccb.geom[2] = static_cast<float>(padH);
    if (!UploadCb(c, c->cbComposite.Get(), &ccb, sizeof(ccb))) {
        return Fail(c, MICA_ERR_DEVICE_LOST, "更新 CompositeCB 失败");
    }
    DrawPass(c, c->psComposite.Get(), c->stageA.srv.Get(), c->cbComposite.Get(),
             c->outTex.rtv.Get(), gridW, gridH);

    UnbindAll(c);

    // --- 回读 -------------------------------------------------------------
    c->ctx->CopyResource(c->readback.Get(), c->outTex.tex.Get());
    D3D11_MAPPED_SUBRESOURCE mapped = {};
    // Map(READ) 会阻塞到 GPU 完成。整条管线的工作量极小（网格 <= 192²），
    // 阻塞时间由驱动往返延迟主导，实测 0.3–1.5 ms。
    const HRESULT hr = c->ctx->Map(c->readback.Get(), 0, D3D11_MAP_READ, 0, &mapped);
    if (FAILED(hr)) {
        if (hr == DXGI_ERROR_DEVICE_REMOVED || hr == DXGI_ERROR_DEVICE_RESET) {
            return FailHr(c, MICA_ERR_DEVICE_LOST, hr, "Map(readback)");
        }
        return FailHr(c, MICA_ERR_INTERNAL, hr, "Map(readback)");
    }

    const uint8_t* base = static_cast<const uint8_t*>(mapped.pData);
    for (int y = 0; y < gridH; ++y) {
        const uint8_t* srcRow = base + static_cast<size_t>(y) * mapped.RowPitch;
        uint8_t* dstRow = outRgb + static_cast<size_t>(y) * static_cast<size_t>(gridW) * 3u;
        for (int x = 0; x < gridW; ++x) {
            // BGRA -> RGB
            dstRow[x * 3 + 0] = srcRow[x * 4 + 2];
            dstRow[x * 3 + 1] = srcRow[x * 4 + 1];
            dstRow[x * 3 + 2] = srcRow[x * 4 + 0];
        }
    }
    c->ctx->Unmap(c->readback.Get(), 0);

    if (outResult != nullptr) {
        outResult->width = gridW;
        outResult->height = gridH;
        outResult->pad_width = padW;
        outResult->pad_height = padH;
        outResult->sample_x = rectX;
        outResult->sample_y = rectY;
        outResult->sample_w = rectW;
        outResult->sample_h = rectH;
        outResult->duration_ms = static_cast<float>(NowMs() - t0);
        outResult->backend = static_cast<int32_t>(c->canvasBackend);
    }
    return MICA_OK;
}

mica_status CanvasMeanRgb(Context* c, uint32_t* outRgb) {
    if (outRgb == nullptr) {
        return Fail(c, MICA_ERR_INVALID_ARG, "out_rgb 为空");
    }
    if (!c->canvas || c->canvasBackend == MICA_BACKEND_NONE) {
        return Fail(c, MICA_ERR_NO_SOURCE, "尚未构建画布");
    }

    if (!c->meanStaging) {
        D3D11_TEXTURE2D_DESC td = {};
        td.Width = static_cast<UINT>(kMeanMipMaxSide);
        td.Height = static_cast<UINT>(kMeanMipMaxSide);
        td.MipLevels = 1;
        td.ArraySize = 1;
        td.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        td.SampleDesc.Count = 1;
        td.Usage = D3D11_USAGE_STAGING;
        td.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        const HRESULT hr = c->device->CreateTexture2D(&td, nullptr, c->meanStaging.Put());
        if (FAILED(hr)) {
            return FailHr(c, MICA_ERR_OUT_OF_MEMORY, hr, "CreateTexture2D(mean staging)");
        }
    }

    // 选出长边 <= kMeanMipMaxSide 的最浅 mip。mip 链在伽马空间逐级取平均，与
    // CPU 版 ``WallpaperSource.mean_rgb`` 对 uint8 求均值的色彩空间一致。
    int level = 0;
    int mipW = (std::max)(c->canvasW, 1);
    int mipH = (std::max)(c->canvasH, 1);
    const int lastLevel = (std::max)(c->canvasMips - 1, 0);
    while (level < lastLevel && (std::max)(mipW, mipH) > kMeanMipMaxSide) {
        ++level;
        mipW = (std::max)(mipW >> 1, 1);
        mipH = (std::max)(mipH >> 1, 1);
    }

    c->ctx->CopySubresourceRegion(c->meanStaging.Get(), 0, 0, 0, 0, c->canvas.Get(),
                                  static_cast<UINT>(level), nullptr);
    D3D11_MAPPED_SUBRESOURCE mapped = {};
    const HRESULT hr = c->ctx->Map(c->meanStaging.Get(), 0, D3D11_MAP_READ, 0, &mapped);
    if (FAILED(hr)) {
        return FailHr(c, MICA_ERR_INTERNAL, hr, "Map(mean staging)");
    }
    uint64_t sumB = 0;
    uint64_t sumG = 0;
    uint64_t sumR = 0;
    const uint8_t* base = static_cast<const uint8_t*>(mapped.pData);
    for (int y = 0; y < mipH; ++y) {
        const uint8_t* row = base + static_cast<size_t>(y) * mapped.RowPitch;
        for (int x = 0; x < mipW; ++x) {
            sumB += row[x * 4 + 0];
            sumG += row[x * 4 + 1];
            sumR += row[x * 4 + 2];
        }
    }
    c->ctx->Unmap(c->meanStaging.Get(), 0);

    const uint64_t n = static_cast<uint64_t>(mipW) * static_cast<uint64_t>(mipH);
    const uint32_t r = static_cast<uint32_t>((sumR + n / 2) / n);
    const uint32_t g = static_cast<uint32_t>((sumG + n / 2) / n);
    const uint32_t b = static_cast<uint32_t>((sumB + n / 2) / n);
    *outRgb = (r << 16) | (g << 8) | b;
    return MICA_OK;
}

}  // namespace mica
