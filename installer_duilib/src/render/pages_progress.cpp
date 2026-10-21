//
// pages_progress.cpp - 安装向导页面⑤「安装进度」与页面⑥「完成」(Todo 11)。
//
// §10：进度值一律 permille 0..1000，百分比 = permille/10.0；真实进度由 Todo 13 引擎
// 经 messages.h 的 WM_INSTALL_PROGRESS 提供，本页只消费，不制造假进度。
// §3：取消只抬高意图 + 切到取消态；引擎安全停止 / 清理 / abort=1 由 Todo 13 负责。
// §15：本文件绝不 ShellExecute；「立即启动」只写 AppState.optLaunch + 抬高完成意图。
// 坐标全程 DIP（§6），控件复用 Todo 7/8，动画经 AnimValue（无动画器时退化为终值）。
//
#include "render/pages_progress.h"

#include <d2d1_1helper.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <utility>

#include "render/logo.h"           // Finish 英雄页图标
#include "render/pages_welcome.h"  // ReadVersionString()（§18 版本单源）
#include "render/render_context.h"  // faf::ComPtr（最小 COM RAII 指针）

namespace faf {

namespace {

// 英雄页（欢迎/完成）大按钮尺寸（DIP）——与 pages_welcome.cpp 保持一致。
constexpr float kHeroButtonW = 200.0f;
constexpr float kHeroButtonH = 44.0f;

// 每个 FinishPage 实例唯一的对勾动画名（同名会复用同一 AnimValue）。
std::atomic<unsigned> g_progressSerial{0};

std::string SerialName(const char* kind, unsigned serial, const char* prop) {
    return std::string(kind) + std::to_string(serial) + "." + prop;
}

// T8：AppState::Operation → ProgressKind（ProgressPage/FinishPage 的便捷重载）。
ProgressKind KindFromOperation(Operation op) {
    switch (op) {
        case Operation::Repair:
            return ProgressKind::Repair;
        case Operation::Uninstall:
            return ProgressKind::Uninstall;
        case Operation::Install:
        default:
            return ProgressKind::Install;
    }
}

// T8：进度页标题。
std::wstring HeadingForKind(ProgressKind kind) {
    switch (kind) {
        case ProgressKind::Repair:
            return L"正在修复 FreeAssetFilter";
        case ProgressKind::Uninstall:
            return L"正在卸载 FreeAssetFilter";
        case ProgressKind::Install:
        default:
            return L"正在安装 FreeAssetFilter";
    }
}

// T8：repair/uninstall 的默认提示（install 无提示）；避免页内硬编码字面量散落。
std::wstring DefaultNotice(ProgressKind kind) {
    switch (kind) {
        case ProgressKind::Repair:
            return L"修复过程中请勿关闭窗口";
        case ProgressKind::Uninstall:
            return L"卸载过程中请勿关闭窗口";
        case ProgressKind::Install:
        default:
            return std::wstring();
    }
}

ComPtr<ID2D1SolidColorBrush> MakeBrush(ID2D1DeviceContext* dc, const D2D1_COLOR_F& color) {
    ComPtr<ID2D1SolidColorBrush> brush;
    if (!dc) return brush;
    dc->CreateSolidColorBrush(color, brush.GetAddressOf());
    return brush;
}

// 绘制文字（默认 NoWrap；wrap=true 用于 Finish 页的非终端 warning）。
void DrawText(ID2D1DeviceContext* dc, const TextFactory* tf, const std::wstring& s,
              const D2D1_RECT_F& rect, float size, DWRITE_FONT_WEIGHT weight,
              DWRITE_TEXT_ALIGNMENT align, const D2D1_COLOR_F& color, bool wrap = false) {
    if (!dc || !tf || !tf->IsReady() || s.empty()) return;
    ComPtr<IDWriteTextFormat> fmt;
    if (FAILED(tf->CreateFormat(size, weight, align, DWRITE_PARAGRAPH_ALIGNMENT_CENTER,
                                fmt.GetAddressOf()))) {
        return;
    }
    fmt->SetWordWrapping(wrap ? DWRITE_WORD_WRAPPING_WRAP : DWRITE_WORD_WRAPPING_NO_WRAP);
    ComPtr<ID2D1SolidColorBrush> brush = MakeBrush(dc, color);
    if (!brush) return;
    dc->DrawText(s.c_str(), static_cast<UINT32>(s.size()), fmt.Get(), rect, brush.Get());
}

// 成功对勾：accent 圆 + 白色描边对勾，随 progress∈[0,1] 逐段「描边绘制」。
// 用两段折线近似对勾；总长 = 段 A + 段 B，按 progress 取部分长度绘制。
// strokeWidth 取半径比例，圆头端点。progress<=0 只画底圆。
void DrawSuccessCheck(ID2D1DeviceContext* dc, float progress, const D2D1_COLOR_F& circleColor,
                      const D2D1_COLOR_F& checkColor, float cx, float cy, float r) {
    if (!dc || r <= 0.0f) return;

    // 已完成底圆（accent）。
    ComPtr<ID2D1SolidColorBrush> circleBrush = MakeBrush(dc, circleColor);
    if (circleBrush) {
        dc->FillEllipse(D2D1::Ellipse(D2D1::Point2F(cx, cy), r, r), circleBrush.Get());
    }

    const float t = std::clamp(progress, 0.0f, 1.0f);
    if (t <= 0.0f) return;

    const D2D1_POINT_2F p0 = D2D1::Point2F(cx - 0.42f * r, cy + 0.02f * r);
    const D2D1_POINT_2F p1 = D2D1::Point2F(cx - 0.12f * r, cy + 0.32f * r);
    const D2D1_POINT_2F p2 = D2D1::Point2F(cx + 0.44f * r, cy - 0.34f * r);

    const float lenA = std::hypot(p1.x - p0.x, p1.y - p0.y);
    const float lenB = std::hypot(p2.x - p1.x, p2.y - p1.y);
    const float total = lenA + lenB;
    if (total <= 0.0f) return;
    const float draw = t * total;

    ComPtr<ID2D1SolidColorBrush> checkBrush = MakeBrush(dc, checkColor);
    if (!checkBrush) return;

    ComPtr<ID2D1StrokeStyle> stroke;
    const float strokeWidth = std::max(2.0f, 0.12f * r);
    const D2D1_STROKE_STYLE_PROPERTIES ssp =
        D2D1::StrokeStyleProperties(D2D1_CAP_STYLE_ROUND, D2D1_CAP_STYLE_ROUND,
                                    D2D1_CAP_STYLE_ROUND, D2D1_LINE_JOIN_ROUND);
    // ID2D1DeviceContext 无 CreateStrokeStyle：经 GetFactory 走 ID2D1Factory。
    {
        ComPtr<ID2D1Factory> factory;
        dc->GetFactory(factory.GetAddressOf());
        if (factory) factory->CreateStrokeStyle(ssp, nullptr, 0, stroke.GetAddressOf());
    }

    auto lerp = [](const D2D1_POINT_2F& a, const D2D1_POINT_2F& b, float u) {
        return D2D1::Point2F(a.x + (b.x - a.x) * u, a.y + (b.y - a.y) * u);
    };

    if (draw <= lenA) {
        const D2D1_POINT_2F end = lerp(p0, p1, draw / lenA);
        dc->DrawLine(p0, end, checkBrush.Get(), strokeWidth, stroke.Get());
    } else {
        dc->DrawLine(p0, p1, checkBrush.Get(), strokeWidth, stroke.Get());
        const float remain = draw - lenA;
        const D2D1_POINT_2F end = lerp(p1, p2, std::min(1.0f, remain / lenB));
        dc->DrawLine(p1, end, checkBrush.Get(), strokeWidth, stroke.Get());
    }
}

}  // namespace

// ============================== 纯函数辅助 =================================

int ProgressStepIndex(int permille) {
    const int p = std::clamp(permille, 0, 1000);
    if (p >= 1000) return 3;  // 完成
    if (p >= 750) return 2;   // 写入快捷方式
    if (p >= 250) return 1;   // 复制文件
    return 0;                 // 初始化
}

std::wstring ProgressStepText(int permille) {
    switch (ProgressStepIndex(permille)) {
        case 0:
            return L"初始化";
        case 1:
            return L"复制文件";
        case 2:
            return L"写入快捷方式";
        default:
            return L"完成";
    }
}

std::wstring ProgressStepText(ProgressKind kind, int permille) {
    const int p = std::clamp(permille, 0, 1000);
    if (kind == ProgressKind::Repair) {
        // 与 Install 同构的 4 段（仅首段文案不同）。
        switch (ProgressStepIndex(p)) {
            case 0:
                return L"准备文件";
            case 1:
                return L"复制文件";
            case 2:
                return L"写入快捷方式";
            default:
                return L"完成";
        }
    }
    if (kind == ProgressKind::Uninstall) {
        // 4 个真实清理阶段 + 完成；阈值与窗口的 stage→permille 映射一致
        //（0/250/500/750/1000），不制造字节级假进度。
        if (p >= 1000) return L"完成";
        if (p >= 750) return L"清理用户数据";
        if (p >= 500) return L"删除程序文件";
        if (p >= 250) return L"清理注册表";
        return L"清理快捷方式";
    }
    return ProgressStepText(p);  // Install：与旧签名完全一致
}

std::wstring ProgressPercentText(int permille) {
    const int p = std::clamp(permille, 0, 1000);
    const double percent = static_cast<double>(p) / 10.0;  // §10：permille/10.0
    wchar_t buf[32] = {};
    swprintf(buf, 32, L"%.1f%%", percent);
    return buf;
}

// ============================== 页面⑤ 安装进度 =============================

ProgressPage::ProgressPage(AppState& state) : state_(state) {
    bar_.SetProgressPermille(0);
    cancelButton_.SetLabel(L"取消");
    cancelButton_.SetGlyph(glyph::Close);
    cancelButton_.SetStyle(Button::Secondary);
    cancelButton_.SetOnClick([this]() { RequestCancel(); });
    host_.Add(&cancelButton_);  // Tab 顺序：仅「取消」可聚焦
}

void ProgressPage::BindAnimator(Animator* animator) {
    cancelButton_.BindAnimator(animator);
    bar_.BindAnimator(animator);
}

void ProgressPage::BindText(const TextFactory* text) {
    text_ = text;
    cancelButton_.BindText(text);
}

void ProgressPage::BindGlyphs(const GlyphFont* glyphs) {
    glyphs_ = glyphs;
    cancelButton_.BindGlyphs(glyphs);
}

void ProgressPage::SetKind(Kind kind) {
    if (kind_ == kind) return;  // 允许宿主逐帧调用；仅在切换时重置提示/stage 文案
    kind_ = kind;
    phase_ = State::Running;
    cancelRequested_ = false;
    stageText_.clear();
    notice_ = DefaultNotice(kind_);
    // T8：repair/uninstall 隐藏取消；install 保持可用。
    SetCancellable(kind_ == Kind::Install);
}

void ProgressPage::SetKind(Operation operation) { SetKind(KindFromOperation(operation)); }

void ProgressPage::SetCancellable(bool cancellable) {
    if (cancellable_ == cancellable) return;
    cancellable_ = cancellable;
    // 隐藏时同时移出 Tab/输入分发；显示时重新加入。
    host_.Clear();
    if (cancellable_) host_.Add(&cancelButton_);
    cancelButton_.SetEnabled(cancellable_ && phase_ == State::Running);
}

void ProgressPage::SetNotice(std::wstring text) { notice_ = std::move(text); }

void ProgressPage::SetStageText(std::wstring text) { stageText_ = std::move(text); }

std::wstring ProgressPage::HeadingText() const { return HeadingForKind(kind_); }

void ProgressPage::SetProgressPermille(int permille) {
    permille_ = std::clamp(permille, 0, 1000);
    bar_.SetProgressPermille(permille_);
}

void ProgressPage::RequestCancel() {
    if (!cancellable_) return;  // T8：repair/uninstall 不允许取消
    if (cancelRequested_) return;
    cancelRequested_ = true;  // 抬高取消意图（无回调宿主的轮询兜底）
    if (phase_ == State::Running) phase_ = State::Cancelling;
    // 通知宿主/引擎请求安全停止（真实停止 + §3 清理 + abort=1 归 Todo 13）。
    if (onCancel_) onCancel_();
}

void ProgressPage::MarkCancelled() {
    // 由 Todo 13 引擎在确认已安全停止并按 §3 清理本次写入后调用。
    cancelRequested_ = true;
    phase_ = State::Cancelled;
}

void ProgressPage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    const float pad = spacing::L;
    const float x0 = contentCard.left + pad;
    const float contentW = (contentCard.right - contentCard.left) - 2.0f * pad;

    // UI-fix：内容块垂直居中（原先固定贴顶 contentCard.top + pad，短内容在卡内显得下坠）。
    // 块高 = 标题 + 步骤行 + 进度条 + 百分比 + 提示行（末行之后不计间距）。
    const float barH = 8.0f;
    const float blockH = (fontsize::Subtitle + spacing::S) + (fontsize::Body + spacing::M) +
                         (barH + spacing::S) + (fontsize::Body + spacing::M) +
                         (fontsize::Body + spacing::S);
    const float cardH = contentCard.bottom - contentCard.top;
    float y = contentCard.top + std::max(spacing::L, (cardH - blockH) * 0.5f);

    headingRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Subtitle + spacing::S);
    y += fontsize::Subtitle + spacing::S;
    stepRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Body + spacing::S);
    y += fontsize::Body + spacing::M;

    barRect_ = D2D1::RectF(x0, y, x0 + contentW, y + barH);
    bar_.SetBounds(barRect_);
    y += barH + spacing::S;
    percentRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Body + spacing::S);
    y += fontsize::Body + spacing::M;

    noticeRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Body + spacing::S);

    // UI-fix：「取消」按钮不再由页内摆放——外壳 LayoutFooterButtons() 统一托管到底部条
    //（页坐标 = 画布 + shadowMarginDip_；取消按钮宽 96、右缘 872、与底部条垂直居中）。
}

void ProgressPage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;

    // UI-fix：恢复单位变换——页布局坐标已是 page coords（= 画布 + shadowMarginDip_），
    // 不重置会叠加外壳预置的 Translation(m,m) 造成 +m 偏移（与其它页的约定一致）。
    dc->SetTransform(D2D1::Matrix3x2F::Identity());

    // 取消进行中 / 已取消时禁用「取消」按钮（repair/uninstall 无「取消」）。
    if (cancellable_) cancelButton_.SetEnabled(phase_ == State::Running);

    DrawText(dc, text_, HeadingText(), headingRect_, fontsize::Subtitle, weight::SemiBold,
             DWRITE_TEXT_ALIGNMENT_LEADING, theme.textPrimary);

    // 步骤文字随 permille 阈值切换（§10）；uninstall 优先使用宿主传入的真实 stage 文案。
    DrawText(dc, text_, L"步骤：" + StepText(), stepRect_, fontsize::Body, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_LEADING, theme.textSecondary);

    bar_.Render(dc, theme);

    DrawText(dc, text_, PercentText(), percentRect_, fontsize::Body, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_LEADING, theme.textPrimary);

    if (phase_ == State::Cancelling) {
        const D2D1_COLOR_F warn = D2D1::ColorF(0.80f, 0.45f, 0.05f, 1.0f);
        DrawText(dc, text_, L"正在安全取消安装……（本次写入的清理由引擎完成）", noticeRect_,
                 fontsize::Caption, weight::Regular, DWRITE_TEXT_ALIGNMENT_LEADING, warn);
    } else if (phase_ == State::Cancelled) {
        const D2D1_COLOR_F fail = D2D1::ColorF(0.85f, 0.20f, 0.20f, 1.0f);
        DrawText(dc, text_, L"安装已取消。", noticeRect_, fontsize::Caption, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_LEADING, fail);
    } else if (!notice_.empty()) {
        // T8：repair/uninstall 的“请勿关闭窗口”等提示；与 stage 文案分离。
        DrawText(dc, text_, notice_, noticeRect_, fontsize::Caption, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_LEADING, theme.textSecondary);
    }

    if (cancellable_) cancelButton_.Render(dc, theme);
}

// ============================== 页面⑥ 完成 ================================

FinishPage::FinishPage(AppState& state) : state_(state) {
    const unsigned serial = g_progressSerial.fetch_add(1, std::memory_order_relaxed);
    checkName_ = SerialName("finish", serial, "check");
    version_ = ReadVersionString();  // §18：只取 FAFVERSION 首行去 'v'，不硬编码
    title_ = productName_;

    // 英雄页大按钮「立即启动」（与欢迎页同构：唯一按钮 = 完成意图 → 去提权启动 + 关窗）。
    finishButton_.SetLabel(L"立即启动");
    finishButton_.SetStyle(Button::Accent);
    finishButton_.SetOnClick([this]() { EmitFinishIntent(); });

    // T8：Repair 专用复选框（默认值来自 AppState，默认 false）；仅 Repair 渲染/参与 Tab。
    launchBox_.SetLabel(L"立即启动 FreeAssetFilter");
    launchBox_.SetChecked(state_.optLaunchAfterRepair);
    launchBox_.SetOnToggle([this](bool checked) { state_.optLaunchAfterRepair = checked; });

    RebuildHost();  // Install 默认仅按钮
}

void FinishPage::RebuildHost() {
    host_.Clear();
    if (kind_ == Kind::Repair) host_.Add(&launchBox_);  // Tab 顺序：复选框 → 按钮
    host_.Add(&finishButton_);
}

void FinishPage::SetKind(Kind kind) {
    kind_ = kind;
    switch (kind_) {
        case Kind::Repair:
            title_ = L"修复完成";
            finishButton_.SetLabel(L"完成");
            launchBox_.SetLabel(L"立即启动 FreeAssetFilter");
            launchBox_.SetChecked(state_.optLaunchAfterRepair);  // 默认 false（T11 已归零）
            break;
        case Kind::Uninstall:
            title_ = L"卸载完成";
            finishButton_.SetLabel(L"关闭");
            break;
        case Kind::Install:
        default:
            title_ = productName_;
            finishButton_.SetLabel(L"立即启动");
            break;
    }
    RebuildHost();
}

void FinishPage::SetKind(Operation operation) { SetKind(KindFromOperation(operation)); }

void FinishPage::SetNotice(std::wstring notice) { notice_ = std::move(notice); }

void FinishPage::BindAnimator(Animator* animator) {
    animator_ = animator;
    finishButton_.BindAnimator(animator);
    launchBox_.BindAnimator(animator);
}

void FinishPage::BindText(const TextFactory* text) {
    text_ = text;
    finishButton_.BindText(text);
    launchBox_.BindText(text);
}

void FinishPage::BindGlyphs(const GlyphFont* glyphs) {
    glyphs_ = glyphs;
    finishButton_.BindGlyphs(glyphs);
    launchBox_.BindGlyphs(glyphs);
}

void FinishPage::StartCheckAnim() {
    if (!animator_) {
        checkFallback_ = 1.0f;  // 无动画器 → 即时终态（harness 无窗口）
        return;
    }
    checkAnim_ = &animator_->Animate(checkName_, 0.0f, 1.0f, 480.0f, easing::Entrance);
    checkFallback_ = 1.0f;
}

float FinishPage::CheckProgress() const {
    if (checkAnim_) return std::clamp(checkAnim_->Value(), 0.0f, 1.0f);
    return checkFallback_;
}

void FinishPage::EmitFinishIntent() {
    finishIntentEmitted_ = true;
    // 仅抬高完成意图；真实启动（§15 去提权）由外壳 OnFinishIntent 执行。
    if (onFinishIntent_) onFinishIntent_();
}

void FinishPage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    noticeRect_ = {};
    const float x0 = contentCard.left + spacing::L;
    const float contentW = (contentCard.right - contentCard.left) - 2.0f * spacing::L;
    const float cx = (contentCard.left + contentCard.right) * 0.5f;
    const float r = 48.0f;  // 对勾圆半径（图标直径 96，与欢迎页 Logo 尺寸一致）
    const float cardH = contentCard.bottom - contentCard.top;

    if (kind_ == Kind::Install) {
        // Install 布局分毫不变（回归要求）：图标 + 名称 + 版本 + 标语 + 大按钮，整体垂直居中。
        const float blockH = (2.0f * r) + spacing::L + (fontsize::Title + spacing::S) +
                             (fontsize::Body + spacing::XS) + (fontsize::Body + spacing::L) +
                             kHeroButtonH;
        float y = contentCard.top + std::max(spacing::L, (cardH - blockH) * 0.5f);

        checkRect_ = D2D1::RectF(cx - r, y, cx + r, y + 2.0f * r);
        y += 2.0f * r + spacing::L;

        nameRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Title + spacing::S);
        y += fontsize::Title + spacing::S;

        versionRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Body + spacing::XS);
        y += fontsize::Body + spacing::XS;

        taglineRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Body + spacing::L);
        y += fontsize::Body + spacing::L;

        buttonRect_ = D2D1::RectF(cx - kHeroButtonW * 0.5f, y, cx + kHeroButtonW * 0.5f,
                                  y + kHeroButtonH);
        finishButton_.SetBounds(buttonRect_);
        return;
    }

    if (kind_ == Kind::Repair) {
        // Repair：对勾 + 「修复完成」+ 版本 + 复选框 + 「完成」。
        const float checkboxH = 24.0f;
        const float blockH = (2.0f * r) + spacing::L + (fontsize::Title + spacing::S) +
                             (fontsize::Body + spacing::XS) + (checkboxH + spacing::L) +
                             kHeroButtonH;
        float y = contentCard.top + std::max(spacing::L, (cardH - blockH) * 0.5f);

        checkRect_ = D2D1::RectF(cx - r, y, cx + r, y + 2.0f * r);
        y += 2.0f * r + spacing::L;

        nameRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Title + spacing::S);
        y += fontsize::Title + spacing::S;

        versionRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Body + spacing::XS);
        y += fontsize::Body + spacing::XS;

        const float checkboxW = 240.0f;
        checkboxRect_ =
            D2D1::RectF(cx - checkboxW * 0.5f, y, cx + checkboxW * 0.5f, y + checkboxH);
        launchBox_.SetBounds(checkboxRect_);
        y += checkboxH + spacing::L;

        buttonRect_ = D2D1::RectF(cx - kHeroButtonW * 0.5f, y, cx + kHeroButtonW * 0.5f,
                                  y + kHeroButtonH);
        finishButton_.SetBounds(buttonRect_);
        return;
    }

    // Uninstall：对勾 + 「卸载完成」+ 可选 warning（非终端提示）+ 「关闭」。
    const float noticeH =
        notice_.empty() ? 0.0f : (2.0f * fontsize::Caption + spacing::S);
    const float blockH = (2.0f * r) + spacing::L + (fontsize::Title + spacing::S) +
                         (notice_.empty() ? spacing::L : (noticeH + spacing::L)) +
                         kHeroButtonH;
    float y = contentCard.top + std::max(spacing::L, (cardH - blockH) * 0.5f);

    checkRect_ = D2D1::RectF(cx - r, y, cx + r, y + 2.0f * r);
    y += 2.0f * r + spacing::L;

    nameRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Title + spacing::S);
    y += fontsize::Title + spacing::S;
    if (!notice_.empty()) {
        noticeRect_ = D2D1::RectF(x0, y, x0 + contentW, y + noticeH);
        y += noticeH + spacing::L;
    } else {
        y += spacing::L;
    }

    buttonRect_ =
        D2D1::RectF(cx - kHeroButtonW * 0.5f, y, cx + kHeroButtonW * 0.5f, y + kHeroButtonH);
    finishButton_.SetBounds(buttonRect_);
}

void FinishPage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;

    // UI-fix：恢复单位变换——页坐标已是绝对值，防止叠加外壳 Translation(m,m) 造成 +m 偏移。
    dc->SetTransform(D2D1::Matrix3x2F::Identity());

    const float cx = (checkRect_.left + checkRect_.right) * 0.5f;
    const float cy = (checkRect_.top + checkRect_.bottom) * 0.5f;
    const float r = (checkRect_.right - checkRect_.left) * 0.5f;
    const D2D1_COLOR_F white = D2D1::ColorF(1.0f, 1.0f, 1.0f, 1.0f);
    DrawSuccessCheck(dc, CheckProgress(), theme.accent, white, cx, cy, r);

    DrawText(dc, text_, title_, nameRect_, fontsize::Title, weight::SemiBold,
             DWRITE_TEXT_ALIGNMENT_CENTER, theme.textPrimary);

    // 版本/标语：Install 原样；Repair 保留版本行；Uninstall 不显示。
    if (kind_ == Kind::Install || kind_ == Kind::Repair) {
        const std::wstring verText =
            version_.empty() ? L"版本：未知（FAFVERSION 资源缺失）" : (L"版本 " + version_);
        DrawText(dc, text_, verText, versionRect_, fontsize::Body, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_CENTER, theme.textSecondary);
    }

    // 标语：仅 Install（与欢迎页完全一致，保证两英雄页文本块内容一致）。
    if (kind_ == Kind::Install && !tagline_.empty()) {
        DrawText(dc, text_, tagline_, taglineRect_, fontsize::Body, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_CENTER, theme.textSecondary);
    }

    // 卸载完成后的 warning 仅作非终端提示，不改变 Finish/关闭语义。
    if (kind_ == Kind::Uninstall && !notice_.empty()) {
        DrawText(dc, text_, notice_, noticeRect_, fontsize::Caption, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_CENTER, theme.textSecondary, true);
    }

    // Repair 专用复选框（安装/卸载不渲染）。
    if (kind_ == Kind::Repair) launchBox_.Render(dc, theme);

    finishButton_.Render(dc, theme);
}

// ============================== Todo 12 接线入口 ===========================

void RenderProgress(ID2D1DeviceContext* dc, const Theme& theme, ProgressPage& page) {
    page.Render(dc, theme);
}

void RenderFinish(ID2D1DeviceContext* dc, const Theme& theme, FinishPage& page) {
    page.Render(dc, theme);
}

}  // namespace faf
