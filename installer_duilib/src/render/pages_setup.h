#pragma once
//
// pages_setup.h - 安装向导页面「安装配置」（安装位置 + 安装选项合并单屏）。
//
// 追加需求（2026-10-18）：原「安装位置」与「安装选项」两页合并为单屏 `ConfigurePage`
//（5 页模型：Welcome / License / Configure / Progress / Finish）。页面状态一律读写
// AppState（Frozen contracts §12），四个安装选项默认值遵循 §2（桌面=1、开始菜单=1、
// 开机自启=0、完成后启动=1）。
//
// 坐标与绘制全程 DIP（§6）：本文件不乘 DPI，由宿主的 ID2D1DeviceContext::SetDpi
// 负责放大。控件全部复用 Todo 7 的 Button / CheckBox / PathField（不重复实现）。
//
// 文件夹选择主路径 = IFileOpenDialog（FOS_PICKFOLDERS）；SHBrowseForFolderW 仅在
// COM 失败时作回退。
//
#include <windows.h>

#include <d2d1_1.h>

#include <string>

#include "render/animation.h"
#include "render/app_state.h"
#include "render/controls_base.h"
#include "render/controls_basic.h"
#include "render/glyphs.h"
#include "render/text.h"
#include "render/theme.h"

namespace faf {

// ============================== 纯函数辅助 =================================

// 人类可读的字节数（1024 进制，>=KB 保留一位小数），如 1536 -> L"1.5 KB"。
// 0 -> L"0 B"。结果始终带单位后缀。纯函数，便于断言。
std::wstring FormatBytes(unsigned long long bytes);

// 递归累加 payloadDir 下常规文件的大小（字节）。目录缺失/不可访问时返回 0。
// 不抛异常（内部捕获 filesystem_error）。
unsigned long long PayloadTotalBytes(const std::wstring& payloadDir);

// 目标盘可用空间（GetDiskFreeSpaceExW 的「调用者可用」值）。`dir` 即使尚不存在也
// 适用——按路径的根（如 `C:\`）查询；无根（相对路径）时退回当前目录。失败返回
// false 且不修改 out。
bool VolumeFreeBytes(const std::wstring& dir, unsigned long long& out);

// 文件夹选择结果（用于可观测性 / 证据）。
enum class FolderPicker {
    Cancelled,        // 用户取消
    IFileOpenDialog,  // 主路径（COM）成功
    ShellBrowse,      // COM 失败 -> SHBrowseForFolderW 回退成功
};

// 打开系统文件夹选择对话框。主路径 = IFileOpenDialog + FOS_PICKFOLDERS；仅当
// COM/IFileOpenDialog 失败时才回退 SHBrowseForFolderW。initialDir 用于预选。
// 成功时 out 收到所选绝对目录。owner 可为 null。
FolderPicker PickInstallFolder(HWND owner, const std::wstring& initialDir, std::wstring& out);

// 写入探针：能否在 dir 下建/删临时文件？dir 尚不存在时改探测「最近的已存在祖先目录」，
// 并以该祖先的可写性作为判定——不创建 dir（仅查看配置页不得产生磁盘副作用）。
// 失败返回 false 并写 errorOut（中文内联文案）。成功时清理探针文件。
bool ProbeWritable(const std::wstring& dir, std::wstring& errorOut);

// ============================== 页面「安装配置」 ===========================

// Configure 页（安装位置 + 安装选项合并）：PathField + 「浏览」按钮 + 所需/可用空间 +
// 不可写内联错误 + 四个安装选项 CheckBox（桌面快捷方式 / 开始菜单 / 开机自启 /
// 完成后启动）。option 状态直接写入 AppState（§12），默认按 §2。
class ConfigurePage {
public:
    explicit ConfigurePage(AppState& state);

    // payload 根目录（所需空间的来源；由宿主经 /payload 提供）。
    void SetPayloadDir(std::wstring dir);

    // 「浏览」按钮点击时需要 HWND 作为对话框 owner；由宿主注入。
    void SetOwner(HWND owner) { owner_ = owner; }

    // 依赖注入（宿主构造后绑定；均可为空——为空时退化为无动画 / 无文字）。
    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text);
    void BindGlyphs(const GlyphFont* glyphs);

    // 依内容卡片矩形（DIP）布局控件——纯几何、零文件系统 I/O（切页/缩放可安全高频调用）。
    void Layout(const D2D1_RECT_F& contentCard);

    // 进入本页钩子（ApplyPageEntry 调用）：SyncFromState + RefreshWritable。
    // 唯一带 I/O 的入口，保证进入配置页时 下一步 门控（CanProceed）即已定妥。
    void OnEnter();

    void Render(ID2D1DeviceContext* dc, const Theme& theme);

    // 输入/Tab 分发宿主（Todo 12 负责事件翻译）。
    WidgetHost& Host() noexcept { return host_; }

    // 从 AppState 同步（如 /installdir 预填后调用）：路径框 + 四个复选框。
    void SyncFromState();
    // 把四个复选框状态写回 AppState（§12）——离开页面/下一步时调用。
    void SyncToState();

    // 打开文件夹选择对话框；成功后回填 AppState.installDir + PathField 并重估可写。
    FolderPicker Browse(HWND owner);

    // 重估目标可写性（写内联错误 + 门控）。返回是否可写。
    bool RefreshWritable();

    // 状态（供 Todo 12 门控「安装」+ 证据断言）。
    bool CanProceed() const noexcept { return canProceed_; }
    bool HasInlineError() const noexcept { return !error_.empty(); }
    const std::wstring& InlineError() const noexcept { return error_; }
    unsigned long long RequiredBytes() const noexcept { return requiredBytes_; }
    unsigned long long FreeBytes() const noexcept { return freeBytes_; }
    const std::wstring& RequiredText() const noexcept { return requiredText_; }
    const std::wstring& FreeText() const noexcept { return freeText_; }
    bool SpaceSufficient() const noexcept { return spaceSufficient_; }

    PathField& Field() noexcept { return pathField_; }
    Button& BrowseButton() noexcept { return browseButton_; }
    CheckBox& DesktopBox() noexcept { return desktop_; }
    CheckBox& StartmenuBox() noexcept { return startmenu_; }
    CheckBox& AutostartBox() noexcept { return autostart_; }
    CheckBox& LaunchBox() noexcept { return launch_; }

private:
    void RecomputeSpace();

    AppState& state_;  // 借用（§12 共享状态）
    std::wstring payloadDir_;
    HWND owner_ = nullptr;

    PathField pathField_;
    Button browseButton_;
    CheckBox desktop_;
    CheckBox startmenu_;
    CheckBox autostart_;
    CheckBox launch_;
    WidgetHost host_;

    const TextFactory* text_ = nullptr;
    const GlyphFont* glyphs_ = nullptr;

    D2D1_RECT_F card_{};
    D2D1_RECT_F headingRect_{};
    D2D1_RECT_F subtitleRect_{};
    D2D1_RECT_F requiredRect_{};
    D2D1_RECT_F freeRect_{};
    D2D1_RECT_F errorRect_{};
    D2D1_RECT_F optionHeadingRect_{};
    D2D1_RECT_F optionSubtitleRect_{};

    unsigned long long payloadTotalBytes_ = 0;  // payload 总字节缓存（仅 SetPayloadDir 遍历一次）
    unsigned long long requiredBytes_ = 0;
    unsigned long long freeBytes_ = 0;
    std::wstring requiredText_;
    std::wstring freeText_;
    std::wstring error_;
    bool spaceSufficient_ = true;
    bool canProceed_ = true;
};

// ============================== Todo 12 接线入口 ===========================

// 页面「安装配置」渲染入口（薄包装，供 Todo 12 调用）。
void RenderConfigure(ID2D1DeviceContext* dc, const Theme& theme, ConfigurePage& page);

}  // namespace faf
