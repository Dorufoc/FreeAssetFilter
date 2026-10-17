//
// pages_setup.cpp - 安装向导页面③「安装位置」与页面④「安装选项」(Todo 10)。
//
// 主路径文件夹选择 = IFileOpenDialog（FOS_PICKFOLDERS）；SHBrowseForFolderW 仅在
// COM 失败时回退。四个安装选项直接读写 AppState（§12），默认值遵循 §2。坐标全程
// DIP（§6），控件复用 Todo 7 的 Button / CheckBox / PathField。
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

#include "render/render_context.h"  // faf::ComPtr

namespace faf {

namespace {

// 绘制一行文字（NoWrap），消费 TextFactory（与 Todo 4 占位不同：走族探测）。
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
    const std::filesystem::path p(dir);
    const std::filesystem::path root = p.root_path();
    std::wstring target;
    if (!root.empty()) {
        target = root.wstring();
    } else {
        std::error_code ec;
        target = std::filesystem::current_path(ec).wstring();
    }
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
            dialog->SetTitle(L"选择 FreeAssetFilter 安装目录");
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
    bi.lpszTitle = L"选择 FreeAssetFilter 安装目录";
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

    std::error_code ec;
    const std::filesystem::path target(dir);
    std::filesystem::create_directories(target, ec);
    if (!std::filesystem::is_directory(target, ec)) {
        errorOut = L"目标位置不可写：无法创建目录";
        return false;
    }

    const std::filesystem::path probe = target / L".faf_write_probe.tmp";
    {
        std::ofstream out(probe.c_str(), std::ios::binary | std::ios::trunc);
        if (!out) {
            errorOut = L"目标位置不可写：没有写入权限";
            return false;
        }
        out.write("p", 1);
        out.flush();
        if (!out.good()) {
            errorOut = L"目标位置不可写：磁盘空间不足";
            return false;
        }
    }
    std::error_code rec;
    std::filesystem::remove(probe, rec);
    return true;
}

// ============================== 页面③ 安装位置 =============================

LocationPage::LocationPage(AppState& state) : state_(state) {
    pathField_.SetPath(state_.installDir);
    browseButton_.SetLabel(L"浏览");
    browseButton_.SetGlyph(glyph::Folder);
    browseButton_.SetStyle(Button::Secondary);
    browseButton_.SetOnClick([this]() { Browse(owner_); });
    host_.Add(&pathField_);    // Tab 顺序：路径框 → 浏览按钮
    host_.Add(&browseButton_);
}

void LocationPage::SetPayloadDir(std::wstring dir) {
    payloadDir_ = std::move(dir);
    RecomputeSpace();
}

void LocationPage::BindAnimator(Animator* animator) { browseButton_.BindAnimator(animator); }

void LocationPage::BindText(const TextFactory* text) {
    text_ = text;
    pathField_.BindText(text);
    browseButton_.BindText(text);
}

void LocationPage::BindGlyphs(const GlyphFont* glyphs) {
    glyphs_ = glyphs;
    browseButton_.BindGlyphs(glyphs);
}

void LocationPage::SyncFromState() { pathField_.SetPath(state_.installDir); }

void LocationPage::RecomputeSpace() {
    requiredBytes_ = PayloadTotalBytes(payloadDir_);
    requiredText_ = FormatBytes(requiredBytes_);
    unsigned long long freeB = 0;
    if (VolumeFreeBytes(state_.installDir, freeB)) {
        freeBytes_ = freeB;
        freeText_ = FormatBytes(freeB);
    } else {
        freeBytes_ = 0;
        freeText_ = L"—";
    }
}

bool LocationPage::RefreshWritable() {
    RecomputeSpace();
    error_.clear();
    if (state_.installDir.empty()) {
        canProceed_ = false;
        return false;
    }
    std::wstring probeErr;
    if (!ProbeWritable(state_.installDir, probeErr)) {
        error_ = probeErr.empty() ? L"目标位置不可写" : probeErr;
        canProceed_ = false;
        return false;
    }
    spaceSufficient_ = (requiredBytes_ == 0) || (freeBytes_ >= requiredBytes_);
    if (!spaceSufficient_) {
        error_ = L"目标磁盘空间不足";
        canProceed_ = false;
        return false;
    }
    canProceed_ = true;
    return true;
}

FolderPicker LocationPage::Browse(HWND owner) {
    std::wstring chosen;
    const FolderPicker result =
        PickInstallFolder(owner ? owner : owner_, state_.installDir, chosen);
    if (result == FolderPicker::Cancelled || chosen.empty()) return FolderPicker::Cancelled;
    state_.installDir = chosen;  // §12：回填 AppState
    pathField_.SetPath(chosen);
    RefreshWritable();
    return result;
}

void LocationPage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    const float pad = spacing::L;
    const float x0 = contentCard.left + pad;
    const float contentW = (contentCard.right - contentCard.left) - 2.0f * pad;

    // UI-fix：内容块垂直居中（原先固定贴顶 contentCard.top + pad，短内容在卡内显得下坠）。
    // 块高 = 标题 + 副标题 + 路径行 + 所需空间 + 可用空间 + 错误行（末行之后不计间距）。
    const float rowH = 32.0f;
    const float blockH = (fontsize::Subtitle + spacing::S) + (fontsize::Caption + spacing::M) +
                         (rowH + spacing::M) + (fontsize::Body + spacing::S) +
                         (fontsize::Body + spacing::S + spacing::S) + (fontsize::Body + spacing::S);
    const float cardH = contentCard.bottom - contentCard.top;
    float y = contentCard.top + std::max(spacing::L, (cardH - blockH) * 0.5f);

    headingRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Subtitle + spacing::S);
    y += fontsize::Subtitle + spacing::S;
    subtitleRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Caption + spacing::S);
    y += fontsize::Caption + spacing::M;

    const float browseW = 88.0f;
    const float gap = spacing::S;
    pathField_.SetBounds(D2D1::RectF(x0, y, x0 + contentW - gap - browseW, y + rowH));
    browseButton_.SetBounds(D2D1::RectF(x0 + contentW - browseW, y, x0 + contentW, y + rowH));
    y += rowH + spacing::M;

    requiredRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Body + spacing::S);
    y += fontsize::Body + spacing::S;
    freeRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Body + spacing::S);
    y += fontsize::Body + spacing::S + spacing::S;
    errorRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Body + spacing::S);

    SyncFromState();
    RefreshWritable();
}

void LocationPage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    DrawText(dc, text_, L"选择安装位置", headingRect_, fontsize::Subtitle, weight::SemiBold,
             DWRITE_TEXT_ALIGNMENT_LEADING, theme.textPrimary);
    DrawText(dc, text_, L"请选择 FreeAssetFilter 的安装目录。", subtitleRect_, fontsize::Caption,
             weight::Regular, DWRITE_TEXT_ALIGNMENT_LEADING, theme.textSecondary);

    pathField_.Render(dc, theme);
    browseButton_.Render(dc, theme);

    DrawText(dc, text_, L"所需空间：" + requiredText_, requiredRect_, fontsize::Body,
             weight::Regular, DWRITE_TEXT_ALIGNMENT_LEADING, theme.textSecondary);
    DrawText(dc, text_, L"目标盘可用空间：" + freeText_, freeRect_, fontsize::Body, weight::Regular,
             DWRITE_TEXT_ALIGNMENT_LEADING, theme.textSecondary);

    if (!error_.empty()) {
        DrawText(dc, text_, error_, errorRect_, fontsize::Body, weight::Regular,
                 DWRITE_TEXT_ALIGNMENT_LEADING, D2D1::ColorF(0.85f, 0.20f, 0.20f, 1.0f));
    }
}

// ============================== 页面④ 安装选项 =============================

OptionsPage::OptionsPage(AppState& state) : state_(state) {
    desktop_.SetLabel(L"创建桌面快捷方式");
    startmenu_.SetLabel(L"添加到开始菜单");
    autostart_.SetLabel(L"开机时自动启动");
    launch_.SetLabel(L"安装完成后立即启动");

    // §12：四个选项直接写入 AppState。
    desktop_.SetOnToggle([this](bool v) { state_.optDesktop = v; });
    startmenu_.SetOnToggle([this](bool v) { state_.optStartmenu = v; });
    autostart_.SetOnToggle([this](bool v) { state_.optAutostart = v; });
    launch_.SetOnToggle([this](bool v) { state_.optLaunch = v; });

    host_.Add(&desktop_);
    host_.Add(&startmenu_);
    host_.Add(&autostart_);
    host_.Add(&launch_);

    SyncFromState();
}

void OptionsPage::BindAnimator(Animator* animator) {
    desktop_.BindAnimator(animator);
    startmenu_.BindAnimator(animator);
    autostart_.BindAnimator(animator);
    launch_.BindAnimator(animator);
}

void OptionsPage::BindText(const TextFactory* text) {
    text_ = text;
    desktop_.BindText(text);
    startmenu_.BindText(text);
    autostart_.BindText(text);
    launch_.BindText(text);
}

void OptionsPage::BindGlyphs(const GlyphFont* glyphs) {
    glyphs_ = glyphs;
    desktop_.BindGlyphs(glyphs);
    startmenu_.BindGlyphs(glyphs);
    autostart_.BindGlyphs(glyphs);
    launch_.BindGlyphs(glyphs);
}

void OptionsPage::SyncFromState() {
    desktop_.SetChecked(state_.optDesktop);
    startmenu_.SetChecked(state_.optStartmenu);
    autostart_.SetChecked(state_.optAutostart);
    launch_.SetChecked(state_.optLaunch);
}

void OptionsPage::SyncToState() {
    state_.optDesktop = desktop_.Checked();
    state_.optStartmenu = startmenu_.Checked();
    state_.optAutostart = autostart_.Checked();
    state_.optLaunch = launch_.Checked();
}

void OptionsPage::Layout(const D2D1_RECT_F& contentCard) {
    card_ = contentCard;
    const float pad = spacing::L;
    const float x0 = contentCard.left + pad;
    const float contentW = (contentCard.right - contentCard.left) - 2.0f * pad;

    // UI-fix：内容块垂直居中（短内容不再固定贴顶；末行之后不计间距）。
    // 块高 = 标题 + 副标题 + 4 个选项行（3 个行距 + 末行本身）。
    const float cbH = 28.0f;
    const float cbGap = spacing::M;
    const float blockH = (fontsize::Subtitle + spacing::S) + (fontsize::Caption + spacing::M) +
                         3.0f * (cbH + cbGap) + cbH;
    const float cardH = contentCard.bottom - contentCard.top;
    float y = contentCard.top + std::max(spacing::L, (cardH - blockH) * 0.5f);

    headingRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Subtitle + spacing::S);
    y += fontsize::Subtitle + spacing::S;
    subtitleRect_ = D2D1::RectF(x0, y, x0 + contentW, y + fontsize::Caption + spacing::S);
    y += fontsize::Caption + spacing::M;

    CheckBox* boxes[4] = {&desktop_, &startmenu_, &autostart_, &launch_};
    for (CheckBox* box : boxes) {
        box->SetBounds(D2D1::RectF(x0, y, x0 + contentW, y + cbH));
        y += cbH + cbGap;
    }

    SyncFromState();
}

void OptionsPage::Render(ID2D1DeviceContext* dc, const Theme& theme) {
    if (!dc) return;
    DrawText(dc, text_, L"安装选项", headingRect_, fontsize::Subtitle, weight::SemiBold,
             DWRITE_TEXT_ALIGNMENT_LEADING, theme.textPrimary);
    DrawText(dc, text_, L"选择安装时创建的附加项。", subtitleRect_, fontsize::Caption,
             weight::Regular, DWRITE_TEXT_ALIGNMENT_LEADING, theme.textSecondary);

    desktop_.Render(dc, theme);
    startmenu_.Render(dc, theme);
    autostart_.Render(dc, theme);
    launch_.Render(dc, theme);
}

// ============================== Todo 12 接线入口 ===========================

void RenderLocation(ID2D1DeviceContext* dc, const Theme& theme, LocationPage& page) {
    page.Render(dc, theme);
}

void RenderOptions(ID2D1DeviceContext* dc, const Theme& theme, OptionsPage& page) {
    page.Render(dc, theme);
}

}  // namespace faf
