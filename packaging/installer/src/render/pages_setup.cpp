//
// pages_setup.cpp - 安装向导页面「安装配置」（安装位置 + 安装选项合并单屏）。
//
// 视觉依据：src/sopeek/resources/icons/install_design/安装配置.svg。
// 主路径文件夹选择 = IFileOpenDialog（FOS_PICKFOLDERS）；SHBrowseForFolderW 仅在
// COM 失败时回退。安装选项直接读写 AppState（§12）。坐标全程 DIP（§6）。
//
#include "render/pages_setup.h"

#include <d2d1_1helper.h>

#include <objbase.h>
#include <shlobj.h>
#include <shobjidl.h>

#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <system_error>

#include "render/layout.h"          // layout::* / PageOffsetDip
#include "render/pages_welcome.h"   // design::* / BaselineRect / kBaselineToBoxTop
#include "render/render_context.h"  // spk::ComPtr

namespace spk {

namespace {

// 绘制一行文字（NoWrap），消费 TextFactory（走族探测）。
void DrawText(ID2D1DeviceContext* dc, const TextFactory* tf, const std::wstring& s,
              const D2D1_RECT_F& rect, float size, DWRITE_FONT_WEIGHT weight,
              DWRITE_TEXT_ALIGNMENT align, const D2D1_COLOR_F& color) {
    if (!dc || !tf || !tf->IsReady() || s.empty()) return;
    ComPtr<IDWriteTextFormat> fmt;
    if (FAILED(tf->CreateFormat(size, weight, align, DWRITE_PARAGRAPH_ALIGNMENT_CENTER,
                                fmt.GetAddressOf()))) {
        return;
    }
    fmt->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP);
    ComPtr<ID2D1SolidColorBrush> brush;
    if (FAILED(dc->CreateSolidColorBrush(color, brush.GetAddressOf()))) return;
    dc->DrawText(s.c_str(), static_cast<UINT32>(s.size()), fmt.Get(), rect, brush.Get());
}

// SHBrowseForFolderW 回退路径的初始化回调：用 lParam 传入的初始路径预选目录。
int CALLBACK BrowseCallbackProc(HWND hwnd, UINT msg, LPARAM /*lp*/, LPARAM data) {
    if (msg == BFFM_INITIALIZED && data) {
        SendMessageW(hwnd, BFFM_SETSELECTIONW, TRUE, data);
    }
    return 0;
}

// 同意行分段文案（纯函数，供排版与绘制共用）。
const wchar_t* kAgreePrefix = L"我已阅读并同意 ";
const wchar_t* kAgreeOss = L"开源协议";
const wchar_t* kAgreeMiddle = L" 和 ";
const wchar_t* kAgreeEula = L"用户协议";

// 目标尚未创建时使用实际最近的目录（也适用于挂载卷与 UNC）。
std::filesystem::path ExistingDirectory(std::filesystem::path path) {
    while (!path.empty()) {
        const DWORD attributes = GetFileAttributesW(path.c_str());
        if (attributes != INVALID_FILE_ATTRIBUTES) {
            return (attributes & FILE_ATTRIBUTE_DIRECTORY) ? path : std::filesystem::path{};
        }
        const DWORD err = GetLastError();
        if (err != ERROR_FILE_NOT_FOUND && err != ERROR_PATH_NOT_FOUND) break;
        const auto parent = path.parent_path();
        if (parent == path) break;
        path = parent;
    }
    return {};
}

}  // namespace

// ============================== 纯函数辅助 =================================

std::wstring FormatBytes(unsigned long long bytes) {
    const wchar_t* units[] = {L"B", L"KB", L"MB", L"GB", L"TB", L"PB"};
    double v = static_cast<double>(bytes);
    int unit = 0;
    while (v >= 1024.0 && unit < 5) {
        v /= 1024.0;
        ++unit;
    }
    wchar_t buf[64] = {};
    if (unit == 0) {
        swprintf(buf, 64, L"%llu B", bytes);
    } else {
        swprintf(buf, 64, L"%.1f %ls", v, units[unit]);
    }
    return buf;
}

unsigned long long PayloadTotalBytes(const std::wstring& payloadDir) {
    if (payloadDir.empty()) return 0;
    std::error_code ec;
    const std::filesystem::path root(payloadDir);
    if (!std::filesystem::is_directory(root, ec)) return 0;
    unsigned long long total = 0;
    try {
        for (const auto& entry : std::filesystem::recursive_directory_iterator(
                 root, std::filesystem::directory_options::skip_permission_denied)) {
            std::error_code fec;
            if (entry.is_regular_file(fec)) total += entry.file_size(fec);
        }
    } catch (const std::filesystem::filesystem_error&) {
        // 部分和仍然可用；不因个别不可访问项放弃整次统计。
    }
    return total;
}

bool VolumeFreeBytes(const std::wstring& dir, unsigned long long& out) {
    const auto target = ExistingDirectory(dir);
    if (target.empty()) return false;
    ULARGE_INTEGER freeToCaller{};
    ULARGE_INTEGER totalBytes{};
    ULARGE_INTEGER totalFree{};
    if (!GetDiskFreeSpaceExW(target.c_str(), &freeToCaller, &totalBytes, &totalFree)) return false;
    out = freeToCaller.QuadPart;
    return true;
}

FolderPicker PickInstallFolder(HWND owner, const std::wstring& initialDir, std::wstring& out) {
    out.clear();

    // ---- 主路径：IFileOpenDialog + FOS_PICKFOLDERS ----
    {
        ComPtr<IFileOpenDialog> dialog;
        const HRESULT createHr = CoCreateInstance(CLSID_FileOpenDialog, nullptr,
                                                  CLSCTX_INPROC_SERVER, __uuidof(IFileOpenDialog),
                                                  dialog.PutVoid());
        if (SUCCEEDED(createHr) && dialog) {
            FILEOPENDIALOGOPTIONS opts = 0;
            if (SUCCEEDED(dialog->GetOptions(&opts))) {
                dialog->SetOptions(opts | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST);
            }
            dialog->SetTitle(L"选择 Sopeek 安装目录");
            if (!initialDir.empty()) {
                ComPtr<IShellItem> folder;
                if (SUCCEEDED(SHCreateItemFromParsingName(initialDir.c_str(), nullptr,
                                                          __uuidof(IShellItem), folder.PutVoid())) &&
                    folder) {
                    dialog->SetFolder(folder.Get());
                }
            }
            const HRESULT showHr = dialog->Show(owner);
            if (showHr == HRESULT_FROM_WIN32(ERROR_CANCELLED)) {
                return FolderPicker::Cancelled;  // 用户取消：不回退、不报错
            }
            if (SUCCEEDED(showHr)) {
                ComPtr<IShellItem> item;
                if (SUCCEEDED(dialog->GetResult(item.GetAddressOf())) && item) {
                    PWSTR psz = nullptr;
                    if (SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH, &psz)) && psz) {
                        out = psz;
                        CoTaskMemFree(psz);
                        return FolderPicker::IFileOpenDialog;
                    }
                }
            }
            // 其它失败：落到 SHBrowseForFolderW 回退。
        }
    }

    // ---- 回退：SHBrowseForFolderW（仅当 COM 主路径未成功时）----
    BROWSEINFOW bi{};
    bi.hwndOwner = owner;
    bi.lpszTitle = L"选择 Sopeek 安装目录";
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
    bi.lpfn = BrowseCallbackProc;
    bi.lParam = initialDir.empty() ? 0 : reinterpret_cast<LPARAM>(initialDir.c_str());
    LPITEMIDLIST id = SHBrowseForFolderW(&bi);
    if (!id) return FolderPicker::Cancelled;
    wchar_t path[MAX_PATH] = {};
    const bool got = SHGetPathFromIDListW(id, path) != FALSE;
    CoTaskMemFree(id);
    if (got && path[0]) {
        out = path;
        return FolderPicker::ShellBrowse;
    }
    return FolderPicker::Cancelled;
}

bool ProbeWritable(const std::wstring& dir, std::wstring& errorOut) {
    errorOut.clear();
    if (dir.empty()) return false;

    const auto parent = ExistingDirectory(dir);
    if (parent.empty()) {
        errorOut = L"目标位置不可写：无法访问目录";
        return false;
    }
    GUID guid{};
    wchar_t name[40]{};
    if (FAILED(CoCreateGuid(&guid)) || !StringFromGUID2(guid, name, 40)) {
        errorOut = L"无法检查目标位置的写入权限";
        return false;
    }
    const auto probe = parent / (std::wstring(L".spk-") + name + L".tmp");
    const HANDLE file = CreateFileW(probe.c_str(), GENERIC_WRITE | DELETE, 0, nullptr,
                                    CREATE_NEW, FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, nullptr);
    if (file == INVALID_HANDLE_VALUE) {
        errorOut = L"目标位置不可写：无法创建临时文件";
        return false;
    }
    CloseHandle(file);
    return true;
}

// ============================== 页面「安装配置」 ===========================

ConfigurePage::ConfigurePage(AppState& state) : state_(state) {
    pathField_.SetPath(state_.installDir);
    pathField_.SetActionLabel(L"浏览");  // 设计稿没有按钮槽：动作内嵌在输入框右侧

    autostart_.SetLabel(L"开机自启动");
    ctxmenu_.SetLabel(L"添加到右键菜单");
    desktop_.SetLabel(L"在桌面创建快捷方式");

    // §12：选项直接写入 AppState。
    autostart_.SetOnToggle([this](bool v) { state_.optAutostart = v; });
    ctxmenu_.SetOnToggle([this](bool v) { state_.optContextMenu = v; });
    desktop_.SetOnToggle([this](bool v) { state_.optDesktop = v; });
    agree_.SetOnToggle([this](bool v) {
        state_.agreed = v;
        RefreshGating();
    });
    // 同意行只用整行命中区（文字自绘，勾选框无标签）。
    agree_.SetLabel(std::wstring());

    nextButton_.SetLabel(L"下一步");
    nextButton_.SetStyle(Button::Accent);
    nextButton_.SetTrailingChevron(true);
    nextButton_.SetOnClick([this]() {
        SyncToState();
        if (onNext_) onNext_();
    });
    backButton_.SetLabel(L"返回");
    backButton_.SetStyle(Button::Secondary);
    backButton_.SetOnClick([this]() {
        SyncToState();
        if (onBack_) onBack_();
    });

    ossLink_.SetLabel(kAgreeOss);
    eulaLink_.SetLabel(kAgreeEula);
    ossLink_.SetStyle(Button::Secondary);
    eulaLink_.SetStyle(Button::Secondary);
    ossLink_.SetOnClick([this]() { if (onOpenDocument_) onOpenDocument_(false); });
    eulaLink_.SetOnClick([this]() { if (onOpenDocument_) onOpenDocument_(true); });

    host_.Add(&pathField_);
    host_.Add(&autostart_);
    host_.Add(&ctxmenu_);
    host_.Add(&desktop_);
    host_.Add(&agree_);
    host_.Add(&ossLink_);
    host_.Add(&eulaLink_);
    host_.Add(&nextButton_);
    host_.Add(&backButton_);

    SyncFromState();
}

void ConfigurePage::SetPayloadDir(std::wstring dir, unsigned long long knownBytes) {
    payloadDir_ = std::move(dir);
    // 生产装配：NSIS 先启动 GUI、后释放载荷，此刻遍历 payload 只能得到「解压到一半」
    // 的部分和（曾导致「所需空间」明显偏小）。因此优先采用 NSIS 传入的构建期精确值
    // （/payload-bytes），完全不扫描；仅当未提供时才回退运行时枚举（测试/独立调用）。
    payloadTotalBytes_ = knownBytes > 0 ? knownBytes : PayloadTotalBytes(payloadDir_);
    RefreshWritable();
}

void ConfigurePage::BindAnimator(Animator* animator) {
    autostart_.BindAnimator(animator);
    ctxmenu_.BindAnimator(animator);
    desktop_.BindAnimator(animator);
    agree_.BindAnimator(animator);
    ossLink_.BindAnimator(animator);
    eulaLink_.BindAnimator(animator);
    nextButton_.BindAnimator(animator);
    backButton_.BindAnimator(animator);
}

void ConfigurePage::BindText(const TextFactory* text) {
    text_ = text;
    pathField_.BindText(text);
    autostart_.BindText(text);
    ctxmenu_.BindText(text);
    desktop_.BindText(text);
    agree_.BindText(text);
    ossLink_.BindText(text);
    eulaLink_.BindText(text);
    nextButton_.BindText(text);
    backButton_.BindText(text);
    LayoutAgreementLine();  // 文字工厂就绪后重算链接命中区
}

void ConfigurePage::BindGlyphs(const GlyphFont* glyphs) {
    glyphs_ = glyphs;
    autostart_.BindGlyphs(glyphs);
    ctxmenu_.BindGlyphs(glyphs);
    desktop_.BindGlyphs(glyphs);
    agree_.BindGlyphs(glyphs);
    nextButton_.BindGlyphs(glyphs);
    backButton_.BindGlyphs(glyphs);
}

void ConfigurePage::SyncFromState() {
    pathField_.SetPath(state_.installDir);
    autostart_.SetChecked(state_.optAutostart);
    ctxmenu_.SetChecked(state_.optContextMenu);
    desktop_.SetChecked(state_.optDesktop);
    agree_.SetChecked(state_.agreed);
    RefreshGating();
}

void ConfigurePage::SyncToState() {
    state_.optAutostart = autostart_.Checked();
    state_.optContextMenu = ctxmenu_.Checked();
    state_.optDesktop = desktop_.Checked();
    state_.agreed = agree_.Checked();
    // 设计稿没有「开始菜单」勾选项：按产品约定始终创建（默认值 1，不露 UI）。
    if (operation_ == Operation::Install) state_.optStartmenu = true;
}

void ConfigurePage::SetMaintenanceMode(Operation operation) {
    operation_ = operation;
    const bool editable = operation == Operation::Install;
    host_.CancelPointer();
    host_.FocusWidget(nullptr);
    pathField_.SetEnabled(editable);
    pathField_.SetActionLabel(editable ? L"浏览" : L"已锁定");
    autostart_.SetEnabled(editable);
    ctxmenu_.SetEnabled(editable);
    desktop_.SetEnabled(editable);
}

void ConfigurePage::RecomputeSpace() {
    requiredBytes_ = payloadTotalBytes_;  // 读缓存——不再在此遍历 payload（见 SetPayloadDir）
    requiredText_ = FormatBytes(requiredBytes_);
    unsigned long long freeB = 0;
    const bool known = VolumeFreeBytes(state_.installDir, freeB);
    spaceSufficient_ = known && freeB >= requiredBytes_;
    if (known) {
        freeBytes_ = freeB;
        freeText_ = FormatBytes(freeB);
    } else {
        freeBytes_ = 0;
        freeText_ = L"—";
    }
}

bool ConfigurePage::RefreshWritable() {
    RecomputeSpace();
    error_.clear();
    if (state_.installDir.empty()) {
        canProceed_ = false;
        RefreshGating();
        return false;
    }
    std::wstring probeErr;
    if (!ProbeWritable(state_.installDir, probeErr)) {
        error_ = probeErr.empty() ? L"目标位置不可写" : probeErr;
        canProceed_ = false;
        RefreshGating();
        return false;
    }
    if (!spaceSufficient_) {
        error_ = freeText_ == L"—" ? L"无法读取目标磁盘空间" : L"目标磁盘空间不足";
        canProceed_ = false;
        RefreshGating();
        return false;
    }
    canProceed_ = true;
    RefreshGating();
    return true;
}

void ConfigurePage::RefreshGating() {
    // 「下一步」只在「目标可写 + 已勾选同意」时可用（设计稿无禁用态，采用 40% 透明）。
    nextButton_.SetEnabled(canProceed_ && state_.agreed);
}

void ConfigurePage::OnEnter() {
    // 进入配置页的 I/O 钩子（由 ApplyPageEntry 调用）：Layout 保持纯几何，I/O 集中在此。
    SyncFromState();
    RefreshWritable();
}

FolderPicker ConfigurePage::Browse(HWND owner) {
    if (operation_ != Operation::Install) return FolderPicker::Cancelled;
    std::wstring chosen;
    const FolderPicker result =
        PickInstallFolder(owner ? owner : owner_, state_.installDir, chosen);
    if (result == FolderPicker::Cancelled || chosen.empty()) return FolderPicker::Cancelled;
    state_.installDir = chosen;  // §12：回填 AppState
    pathField_.SetPath(chosen);
    RefreshWritable();
    return result;
}

float ConfigurePage::Measure(const std::wstring& s, float size, DWRITE_FONT_WEIGHT weight) const {
    if (!text_ || !text_->IsReady() || s.empty()) return 0.0f;
    IDWriteFactory* factory = text_->Factory();
    if (!factory) return 0.0f;
    ComPtr<IDWriteTextFormat> fmt;
    if (FAILED(text_->CreateFormat(size, weight, DWRITE_TEXT_ALIGNMENT_LEADING,
                                   DWRITE_PARAGRAPH_ALIGNMENT_CENTER, fmt.GetAddressOf()))) {
        return 0.0f;
    }
    fmt->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP);
    ComPtr<IDWriteTextLayout> layout;
    if (FAILED(factory->CreateTextLayout(s.c_str(), static_cast<UINT32>(s.size()), fmt.Get(),
                                         4096.0f, size * 2.0f, layout.GetAddressOf()))) {
        return 0.0f;
    }
    DWRITE_TEXT_METRICS metrics{};
    if (FAILED(layout->GetMetrics(&metrics))) return 0.0f;
    return metrics.widthIncludingTrailingWhitespace;
}

void ConfigurePage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;

    // 设计稿：页标题中心 x=102（tspan -64 = 半字宽），标签中心 x=75。
    titleRect_ = CenteredBaselineRect(design::kPageTitleCenterX, design::kPageTitleBaselineY,
                                      fontsize::PageTitle);
    fieldLabelRect_ = CenteredBaselineRect(design::kFieldLabelCenterX,
                                           design::kFieldLabelBaselineY, fontsize::Body16);

    pathField_.SetBounds(D2D1::RectF(layout::kContentLeft, design::kFieldTop,
                                     layout::kContentLeft + layout::kContentWidth,
                                     design::kFieldTop + design::kFieldHeight));

    spaceRect_ = BaselineRect(design::kSpaceLeft, layout::kContentLeft + layout::kContentWidth,
                              design::kSpaceBaselineY, fontsize::Body16);
    // 错误在选项与协议之间独立占行，容量信息始终完整显示。
    errorRect_ = BaselineRect(design::kSpaceLeft,
                              layout::kContentLeft + layout::kContentWidth,
                              334.0f, fontsize::Body16);

    // 三个复选项：盒子左缘取设计稿实测值，命中区向右扩到标签末尾。
    struct OptionRow {
        CheckBox* box;
        float left;
    };
    const OptionRow rows[3] = {{&autostart_, design::kOptionAutostartLeft},
                               {&ctxmenu_, design::kOptionCtxMenuLeft},
                               {&desktop_, design::kOptionDesktopLeft}};
    for (const OptionRow& row : rows) {
        const float labelW = Measure(row.box->Label(), fontsize::Body16, weight::Regular);
        const float width = 29.0f + 8.0f + labelW + 8.0f;
        row.box->SetBounds(D2D1::RectF(row.left, design::kOptionBoxTop, row.left + width,
                                       design::kOptionBoxTop + 29.0f));
    }

    // 同意行：勾选框尺寸 29，整行命中；文字从盒子右缘 + 8 开始。
    agreeLineRect_ = D2D1::RectF(design::kAgreeBoxLeft, design::kAgreeBoxTop,
                                 layout::kContentLeft + layout::kContentWidth,
                                 design::kAgreeBoxTop + 29.0f);
    LayoutAgreementLine();

    nextButton_.SetBounds(D2D1::RectF(design::kButtonLeft, design::kButtonTop,
                                      design::kButtonLeft + design::kButtonWidth,
                                      design::kButtonTop + design::kButtonHeight));
    backButton_.SetBounds(CenteredBaselineRect(design::kActionCenterX, design::kLinkBaselineY,
                                               fontsize::Body16, 30.0f));

    RefreshGating();
}

void ConfigurePage::LayoutAgreementLine() {
    const float x0 = agreeLineRect_.left + 29.0f + 8.0f;
    const float baseline = design::kAgreeBaselineY;
    const float size = fontsize::Body16;
    const float w1 = Measure(kAgreePrefix, size, weight::Regular);
    const float w2 = Measure(kAgreeOss, size, weight::Regular);
    const float w3 = Measure(kAgreeMiddle, size, weight::Regular);
    const float w4 = Measure(kAgreeEula, size, weight::Regular);

    agreePrefixRect_ = BaselineRect(x0, x0 + w1, baseline, size);
    agree_.SetBounds(D2D1::RectF(agreeLineRect_.left, agreeLineRect_.top,
                                agreePrefixRect_.right, agreeLineRect_.bottom));
    ossLink_.SetBounds(BaselineRect(x0 + w1, x0 + w1 + w2, baseline, size));
    agreeMiddleRect_ = BaselineRect(x0 + w1 + w2, x0 + w1 + w2 + w3, baseline, size);
    eulaLink_.SetBounds(BaselineRect(x0 + w1 + w2 + w3, x0 + w1 + w2 + w3 + w4, baseline, size));
}

void ConfigurePage::DrawAgreementLine(ID2D1DeviceContext* dc, const Theme& theme) {
    const float size = fontsize::Body16;
    D2D1_COLOR_F ink = theme.textPrimary;
    DrawText(dc, text_, kAgreePrefix, agreePrefixRect_, size, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_LEADING, ink);
    ossLink_.Render(dc, theme);
    DrawText(dc, text_, kAgreeMiddle, agreeMiddleRect_, size, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_LEADING, ink);
    eulaLink_.Render(dc, theme);
}

bool ConfigurePage::OnInput(const InputEvent& event) {
    const bool consumed = host_.Dispatch(event);

    // 路径框内任意点击 = 打开文件夹选择（设计稿没有独立「浏览」按钮）。
    if (pathField_.TakeActivated()) {
        Browse(owner_);
        return true;
    }
    return consumed;
}

void ConfigurePage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    const D2D1_POINT_2F o = PageOffsetDip(card_);
    D2D1_MATRIX_3X2_F parent{};
    dc->GetTransform(&parent);
    dc->SetTransform(D2D1::Matrix3x2F::Translation(o.x, o.y) * parent);

    const wchar_t* heading = operation_ == Operation::Update ? L"更新配置" :
                             operation_ == Operation::Repair ? L"修复配置" : L"安装配置";
    DrawText(dc, text_, heading, titleRect_, fontsize::PageTitle, weight::Bold,
             DWRITE_TEXT_ALIGNMENT_CENTER, theme.textPrimary);
    DrawText(dc, text_, L"安装路径", fieldLabelRect_, fontsize::Body16, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_CENTER, theme.textPrimary);

    pathField_.Render(dc, theme);

    const std::wstring space = L"可用空间：" + freeText_ + L"    预计所需 " + requiredText_;
    DrawText(dc, text_, space, spaceRect_, fontsize::Body16, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_LEADING, theme.textPrimary);

    if (!error_.empty()) {
        DrawText(dc, text_, error_, errorRect_, fontsize::Body16, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_LEADING, theme.errorText);
    }

    autostart_.Render(dc, theme);
    ctxmenu_.Render(dc, theme);
    desktop_.Render(dc, theme);
    agree_.Render(dc, theme);
    DrawAgreementLine(dc, theme);

    nextButton_.Render(dc, theme);
    backButton_.Render(dc, theme);
}

// ============================== 接线入口 ===================================

void RenderConfigure(ID2D1DeviceContext* dc, const Theme& theme, ConfigurePage& page) {
    page.Render(dc, theme);
}

}  // namespace spk
