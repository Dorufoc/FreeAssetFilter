#pragma once
//
// pages_setup.h - 安装向导页面「安装配置」（安装位置 + 安装选项合并单屏）。
//
// 视觉唯一依据：`src/sopeek/resources/icons/install_design/安装配置.svg`。
// 画布 640x540 DIP（design 坐标减 (640,268)）：
//   标题「安装配置」        32px bold / 基线 114 / 左缘 102
//   「安装路径」            16px / 基线 169 / 左缘 75
//   路径框 564x36 r8        (38,180)，右侧内嵌「浏览」文字，18px #878787 路径
//   「可用空间：… 预计所需 …」16px / 基线 240 / 左缘 43
//   三个复选项 29px         (44/223/415, 267)，标签 16px 基线 287
//   同意行                  复选框 (167,375)，文字 16px 基线 395 / 左缘 204
//   黑色胶囊「下一步 >」     152x36 (244,427)
//   「返回」文字链接          16px 基线 503 / 水平居中
//
// 设计稿的文字对象以 x=960（窗口中心）作为左边缘，导致整体右偏；经用户确认按
// 「真正居中」实现（字号/字重/几何不变）。同意行的「开源协议」「用户协议」是
// 可点击链接（悬停加下划线），点击后进入独立协议阅读页。
//
// 页面状态一律读写 AppState（Frozen contracts §12）。坐标/绘制全程 DIP（§6）。
//
#include <windows.h>

#include <d2d1_1.h>

#include <functional>
#include <string>

#include "render/animation.h"
#include "render/app_state.h"
#include "render/controls_base.h"
#include "render/controls_basic.h"
#include "render/glyphs.h"
#include "render/text.h"
#include "render/theme.h"

namespace spk {

// ============================== 纯函数辅助 =================================

// 人类可读的字节数（1024 进制，>=KB 保留一位小数），如 1536 -> L"1.5 KB"。
// 0 -> L"0 B"。结果始终带单位后缀。纯函数，便于断言。
std::wstring FormatBytes(unsigned long long bytes);

// 递归累加 payloadDir 下常规文件的大小（字节）。目录缺失/不可访问时返回 0。
// 不抛异常（内部捕获 filesystem_error）。
unsigned long long PayloadTotalBytes(const std::wstring& payloadDir);

// 目标盘可用空间（GetDiskFreeSpaceExW 的「调用者可用」值）。`dir` 即使尚不存在也
// 适用——按实际最近的已存在目录查询，支持挂载点。失败返回
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

// 配置页：路径框 + 三个安装选项（开机自启动 / 添加到右键菜单 / 桌面快捷方式）
// + 同意勾选（含「开源协议」「用户协议」链接）+ 下一步 / 返回。
class ConfigurePage {
public:
    explicit ConfigurePage(AppState& state);

    // payload 根目录（所需空间的来源；由宿主经 /payload 提供）。
    // knownBytes > 0 时直接采用（NSIS 传入的构建期精确值，GUI 先于载荷解压启动，
    // 运行时遍历只能得到部分和）；0 表示未知，回退为运行时枚举。
    void SetPayloadDir(std::wstring dir, unsigned long long knownBytes = 0);

    // 「浏览」需要 HWND 作为对话框 owner；由宿主注入。
    void SetOwner(HWND owner) { owner_ = owner; }

    // 依赖注入（宿主构造后绑定；均可为空——为空时退化为无动画 / 无文字）。
    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text);
    void BindGlyphs(const GlyphFont* glyphs);

    // 依内容卡片矩形布局控件——纯几何、零文件系统 I/O（切页/缩放可安全高频调用）。
    void Layout(const D2D1_RECT_F& contentCard);

    // 进入本页钩子（ApplyPageEntry 调用）：SyncFromState + RefreshWritable。
    // 唯一带 I/O 的入口，保证进入配置页时 下一步 门控（CanProceed）即已定妥。
    void OnEnter();
    // 更新与修复显示已保存的配置，只允许重新确认协议。
    void SetMaintenanceMode(Operation operation);

    void Render(ID2D1DeviceContext* dc, const Theme& theme);

    // 输入/Tab 分发宿主（Tab 顺序：路径框 → 三个选项 → 同意 → 下一步 → 返回）。
    WidgetHost& Host() noexcept { return host_; }

    bool OnInput(const InputEvent& event);

    // 从 AppState 同步（如 /installdir 预填后调用）：路径框 + 三个复选框 + 同意。
    void SyncFromState();
    // 把三个复选框状态写回 AppState（§12）——离开页面/下一步时调用。
    void SyncToState();

    // 打开文件夹选择对话框；成功后回填 AppState.installDir + PathField 并重估可写。
    FolderPicker Browse(HWND owner);

    // 重估目标可写性（写内联错误 + 门控）。返回是否可写。
    bool RefreshWritable();
    // 依 canProceed_/agreed 刷新「下一步」可用性（外壳与页内都会调用）。
    void RefreshGating();

    // 页面意图（由外壳注入）。
    void SetOnNext(std::function<void()> cb) { onNext_ = std::move(cb); }
    void SetOnBack(std::function<void()> cb) { onBack_ = std::move(cb); }
    // kind: false = 开源协议（AGPL 全文），true = 用户协议。
    void SetOnOpenDocument(std::function<void(bool userAgreement)> cb) {
        onOpenDocument_ = std::move(cb);
    }

    // 状态（供外壳门控「安装」+ 证据断言）。
    bool CanProceed() const noexcept { return canProceed_ && state_.agreed; }
    bool PathWritable() const noexcept { return canProceed_; }
    bool HasInlineError() const noexcept { return !error_.empty(); }
    const std::wstring& InlineError() const noexcept { return error_; }
    const std::wstring& RequiredText() const noexcept { return requiredText_; }
    const std::wstring& FreeText() const noexcept { return freeText_; }
    bool SpaceSufficient() const noexcept { return spaceSufficient_; }

    PathField& Field() noexcept { return pathField_; }
    CheckBox& AutostartBox() noexcept { return autostart_; }
    CheckBox& ContextMenuBox() noexcept { return ctxmenu_; }
    CheckBox& DesktopBox() noexcept { return desktop_; }
    CheckBox& AgreeBox() noexcept { return agree_; }
    Button& NextButton() noexcept { return nextButton_; }
    Button& BackButton() noexcept { return backButton_; }

private:
    void RecomputeSpace();
    float Measure(const std::wstring& s, float size, DWRITE_FONT_WEIGHT weight) const;
    void LayoutAgreementLine();
    void DrawAgreementLine(ID2D1DeviceContext* dc, const Theme& theme);

    AppState& state_;  // 借用（§12 共享状态）
    Operation operation_ = Operation::Install;
    std::wstring payloadDir_;
    HWND owner_ = nullptr;

    PathField pathField_;
    CheckBox autostart_;
    CheckBox ctxmenu_;
    CheckBox desktop_;
    CheckBox agree_;
    Button ossLink_;
    Button eulaLink_;
    Button nextButton_;
    Button backButton_;
    WidgetHost host_;

    const TextFactory* text_ = nullptr;
    const GlyphFont* glyphs_ = nullptr;

    D2D1_RECT_F card_{};
    D2D1_RECT_F titleRect_{};
    D2D1_RECT_F fieldLabelRect_{};
    D2D1_RECT_F spaceRect_{};
    D2D1_RECT_F errorRect_{};
    // 同意行分段（前缀 / 开源协议 / 中间 / 用户协议）与其命中矩形。
    D2D1_RECT_F agreePrefixRect_{};
    D2D1_RECT_F agreeMiddleRect_{};
    D2D1_RECT_F agreeLineRect_{};
    int hoveredLink_ = 0;  // 0 = 无，1 = 开源协议，2 = 用户协议

    unsigned long long payloadTotalBytes_ = 0;  // payload 总字节缓存（仅 SetPayloadDir 遍历一次）
    unsigned long long requiredBytes_ = 0;
    unsigned long long freeBytes_ = 0;
    std::wstring requiredText_;
    std::wstring freeText_;
    std::wstring error_;
    bool spaceSufficient_ = true;
    bool canProceed_ = true;
    bool pathActivatedArmed_ = false;

    std::function<void()> onNext_;
    std::function<void()> onBack_;
    std::function<void(bool)> onOpenDocument_;
};

// ============================== 接线入口 ===================================

// 页面「安装配置」渲染入口（薄包装，供 installer_window 调用）。
void RenderConfigure(ID2D1DeviceContext* dc, const Theme& theme, ConfigurePage& page);

}  // namespace spk
