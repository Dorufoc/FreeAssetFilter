#pragma once
//
// pages_maintenance.h - 维护 / 卸载确认 / 通用消息三个英雄页（T7）。
//
// 契约来源：计划 T7、D6/D7、D15 C3（用户数据唯一模型）。三页均为英雄页（无顶部
// 步骤带、无底部导航条），几何一律由 InstallerWindow 传入的 `contentCard` 计算，
// 页面内按钮/复选框自行摆放——外壳 `LayoutFooterButtons` 不会摆放它们。
//
// 依赖模式与 pages_welcome / pages_setup 保持一致：
//   * 构造后由宿主注入 Animator / TextFactory / GlyphFont（均可为空——为空时控件
//     退化为无动画 / 无文字，绝不会崩溃）；
//   * `Layout(contentCard)` 只做纯几何计算，不做任何 I/O；
//   * `Render(dc, theme)` 使用配置页的主题与字号，只在绘制时平移 PageOffsetDip；
//   * `Host()` 返回页面唯一的 WidgetHost（注册顺序即 Tab 顺序），输入与 Tab 分发
//     复用 controls_base.h 的既有路径。
//
// 坐标与绘制全程 DIP（§6）：本文件不乘 DPI。
//
// 页面职责边界（T7 只做 UI，不写文件系统/注册表）：
//   * MaintenancePage       —— 展示已安装信息，抬高修复/卸载/取消意图；
//   * UninstallConfirmPage  —— 删除范围说明 + 「同时删除用户数据」复选框；
//   * MessagePage           —— 通用标题/正文/主次按钮 + busy 态（隐藏并禁用按钮）。
//
// T10 接线方式（与既有页面一致）：
//   maintenancePage_ = std::make_unique<spk::MaintenancePage>(state_);
//   maintenancePage_->BindAnimator(&animator_);
//   maintenancePage_->BindText(&textFactory_);
//   maintenancePage_->BindGlyphs(&glyphFont_);
//   ...
//   spk::RenderMaintenance(ctx, theme, *maintenancePage_);
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

class LogoBitmap;

// ============================== Maintenance 页（Page=5） ====================

// 新版本显示更新和修复，同版本显示修复和卸载，卸载入口仅显示卸载。
class MaintenancePage {
public:
    // state 仅借用（读取初值），生命周期必须长于本页。
    explicit MaintenancePage(AppState& state);

    // ---- 依赖注入（宿主构造后绑定；均可为空，为空时安全退化）----
    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text);
    void BindGlyphs(const GlyphFont* glyphs);

    void SetInfo(std::wstring installDir, std::wstring version, bool detected, bool complete);
    void SetOffer(MaintenanceOffer offer);
    void SetBackground(const LogoBitmap* background) { background_ = background; }

    // ---- 意图回调（均为无参 void()；由 T11 注入）----
    void SetOnUpdate(std::function<void()> cb);
    void SetOnRepair(std::function<void()> cb);
    void SetOnUninstall(std::function<void()> cb);
    void SetOnCancel(std::function<void()> cb);

    // 依内容卡片矩形（DIP）布局；纯几何、可在切页/缩放时高频调用。
    void Layout(const D2D1_RECT_F& contentCard);

    // 绘制页面（按钮在页面内自行绘制，不经外壳底部条）。
    void Render(ID2D1DeviceContext* dc, const Theme& theme);

    // 输入 / Tab 分发宿主（T10 的 ActivePageHost 使用）。
    WidgetHost& Host() noexcept { return host_; }

    // 只读状态（供 T11 / 截图工具 / 验收断言）。
    const std::wstring& InstallDir() const noexcept { return installDir_; }
    const std::wstring& Version() const noexcept { return version_; }
    bool Detected() const noexcept { return detected_; }
    bool Complete() const noexcept { return complete_; }

    Button& UpdateButton() noexcept { return updateButton_; }
    Button& RepairButton() noexcept { return repairButton_; }
    Button& UninstallButton() noexcept { return uninstallButton_; }
    Button& CancelButton() noexcept { return cancelButton_; }

private:
    void UpdateActions();
    void RelayoutIfReady();

    std::wstring installDir_;
    std::wstring version_;
    bool detected_ = false;
    bool complete_ = false;

    MaintenanceOffer offer_ = MaintenanceOffer::Repair;
    Button updateButton_;
    Button repairButton_;
    Button uninstallButton_;
    Button cancelButton_;
    WidgetHost host_;

    const TextFactory* text_ = nullptr;
    const LogoBitmap* background_ = nullptr;

    std::function<void()> onUpdate_;
    std::function<void()> onRepair_;
    std::function<void()> onUninstall_;
    std::function<void()> onCancel_;

    D2D1_RECT_F card_{};
    D2D1_RECT_F titleRect_{};
    D2D1_RECT_F detailRect_{};
};

// ============================== UninstallConfirm 页（Page=6） ==============

// 卸载欢迎与选项页复用同一布局实现，数据删除选项只出现在第二页。
class UninstallConfirmPage {
public:
    // state 仅借用；生命周期必须长于本页。
    explicit UninstallConfirmPage(AppState& state);

    // ---- 依赖注入（宿主构造后绑定；均可为空，为空时安全退化）----
    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text);
    void BindGlyphs(const GlyphFont* glyphs);

    void SetBackground(const LogoBitmap* background) { background_ = background; }
    void SetChecklist(bool checklist);

    // ---- 意图回调（均为无参 void()；由 T12 注入）----
    void SetOnConfirm(std::function<void()> cb);
    void SetOnCancel(std::function<void()> cb);

    // state_.deleteUserData → 复选框。
    void SyncFromState();
    // 复选框 → state_.deleteUserData。
    void SyncToState();

    // 依内容卡片矩形（DIP）布局；纯几何。
    void Layout(const D2D1_RECT_F& contentCard);
    void Render(ID2D1DeviceContext* dc, const Theme& theme);

    WidgetHost& Host() noexcept { return host_; }

    // 只读状态 / 控件访问（供 T12 与验收断言）。
    bool DeleteUserData() const;
    CheckBox& DeleteUserDataBox() noexcept { return deleteUserData_; }
    Button& ConfirmButton() noexcept { return confirmButton_; }
    Button& CancelButton() noexcept { return cancelButton_; }

private:
    AppState& state_;  // 借用（§12 共享状态）
    CheckBox deleteUserData_;
    Button confirmButton_;
    Button cancelButton_;
    WidgetHost host_;

    const TextFactory* text_ = nullptr;

    const LogoBitmap* background_ = nullptr;
    bool checklist_ = true;

    std::function<void()> onConfirm_;
    std::function<void()> onCancel_;

    D2D1_RECT_F card_{};
    D2D1_RECT_F titleRect_{};
};

// ============================== Message 页（Page=7） =======================

// 通用消息页（英雄页）：标题 + 正文（自动换行）+ 主/次按钮。
//
// 用于：「正在关闭 Sopeek…」「无法关闭」「卸载未完成」「未找到已安装版本」
// 等所有需要用户知情/决策的路径（T13 的 ShowError 封装到 SetContent）。
//
// 按钮规则：
//   * primaryLabel 非空才显示主按钮（Accent）；
//   * showSecondary == true 且 secondaryLabel 非空才显示次按钮（Secondary）；
//   * SetBusy(true, text) 时**隐藏并禁用**两个按钮，仅保留正文 + busy 文案；
//     SetBusy(false) 恢复。
//
// 构造：`MessagePage()` 与 `MessagePage(AppState&)` 两种均可（后者仅为与其它页面
// 统一构造形式，本页不读写 AppState）。
class MessagePage {
public:
    MessagePage();
    explicit MessagePage(AppState& state);

    // ---- 依赖注入（宿主构造后绑定；均可为空，为空时安全退化）----
    void BindAnimator(Animator* animator);
    void BindText(const TextFactory* text);
    void BindGlyphs(const GlyphFont* glyphs);

    // 设置内容。`showSecondary` 决定次按钮是否参与布局/渲染（标签为空时仍隐藏）。
    // 本调用不会清除 busy 态；需恢复按钮请显式 SetBusy(false)。
    void SetContent(std::wstring title, std::wstring body, std::wstring primaryLabel,
                    std::wstring secondaryLabel, bool showSecondary);

    // ---- 意图回调（均为无参 void()；由 T11/T12/T13 注入）----
    void SetOnPrimary(std::function<void()> cb);
    void SetOnSecondary(std::function<void()> cb);

    // busy 态：隐藏并禁用按钮，只显示正文；`text` 作为附加状态行（仅 busy 时显示）。
    void SetBusy(bool busy, std::wstring text = std::wstring());

    // 依内容卡片矩形（DIP）布局；纯几何。SetContent / SetBusy 后若已布局会自动重排。
    void Layout(const D2D1_RECT_F& contentCard);
    void Render(ID2D1DeviceContext* dc, const Theme& theme);

    WidgetHost& Host() noexcept { return host_; }

    // 只读状态（供 T11/T12/T13 与验收断言）。
    const std::wstring& Title() const noexcept { return title_; }
    const std::wstring& Body() const noexcept { return body_; }
    const std::wstring& BusyText() const noexcept { return busyText_; }
    bool Busy() const noexcept { return busy_; }
    bool PrimaryVisible() const;
    bool SecondaryVisible() const;

    Button& PrimaryButton() noexcept { return primaryButton_; }
    Button& SecondaryButton() noexcept { return secondaryButton_; }

private:
    void UpdateButtonStates();
    void RelayoutIfReady();

    std::wstring title_;
    std::wstring body_;
    std::wstring primaryLabel_;
    std::wstring secondaryLabel_;
    bool showSecondary_ = false;
    bool busy_ = false;
    std::wstring busyText_;

    Button primaryButton_;
    Button secondaryButton_;
    WidgetHost host_;

    const TextFactory* text_ = nullptr;

    std::function<void()> onPrimary_;
    std::function<void()> onSecondary_;

    D2D1_RECT_F card_{};
    D2D1_RECT_F titleRect_{};
    D2D1_RECT_F bodyRect_{};
    D2D1_RECT_F busyRect_{};
    D2D1_RECT_F primaryRect_{};
    D2D1_RECT_F secondaryRect_{};
};

// ============================== T10 接线入口 ===============================

// 三个英雄页的渲染薄包装（与 RenderWelcome / RenderConfigure / RenderProgress 同构）。
void RenderMaintenance(ID2D1DeviceContext* dc, const Theme& theme, MaintenancePage& page);
void RenderUninstallConfirm(ID2D1DeviceContext* dc, const Theme& theme,
                            UninstallConfirmPage& page);
void RenderMessage(ID2D1DeviceContext* dc, const Theme& theme, MessagePage& page);

}  // namespace spk
