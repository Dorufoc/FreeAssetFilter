#pragma once
//
// maintenance_protocol.h - 维护/修复/卸载跨进程协议的**唯一常量来源**（T1）。
//
// 本文件只包含编译期常量与枚举，不含任何平台实现、不配套 .cpp。后续所有 C++
// 模块（MaintenanceDetector / SingleInstance / UninstallProtocol / InstallerWindow
// 等）必须从这里取注册表键、互斥体名、INI 文件名/键名、stage 与超时值，禁止在
// 多个 .cpp 中重复字符串字面量。
//
// 契约来源：计划 D1/D2/D3/D5/D9/D10/D11/D13 与 D15（C1-C4、M2、H5）。
// 发生冲突时以 D15 为准。
//
#include <cstdint>

namespace faf::protocol {

// 测试构建由 CMake -DFAF_TESTMODE=ON 注入（cmake/test_mode.cmake）；生产构建该宏未定义。
#ifdef FAF_TESTMODE
inline constexpr bool kTestMode = true;
#else
inline constexpr bool kTestMode = false;
#endif

// ---------------------------------------------------------------------------
// 注册表键（D13 测试隔离）
// ---------------------------------------------------------------------------

// 安装信息键（位于 HKCU / HKEY_CURRENT_USER）：
//   InstallDir / InstallLocation / OptDesktop / OptStartmenu / OptAutostart / Version。
inline constexpr wchar_t kInstallInfoKeyProd[] = L"Software\\FreeAssetFilter";
inline constexpr wchar_t kInstallInfoKeyTest[] = L"Software\\FreeAssetFilterTest";
inline constexpr const wchar_t* kInstallInfoKey =
    kTestMode ? kInstallInfoKeyTest : kInstallInfoKeyProd;

// 卸载键（Add/Remove Programs）：
//   生产 = HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter
//          64 位视图（NSIS 配合 SetRegView 64；C++ 使用 KEY_WOW64_64KEY）。
//   测试 = HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest
//          （与 installer.nsi 现有测试分支、D13/T16 一致；HKCU\...\Uninstall
//          不受 WOW64 重定向，测试绝不触碰生产键）。
inline constexpr wchar_t kUninstallKeyProd[] =
    L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\FreeAssetFilter";
inline constexpr wchar_t kUninstallKeyTest[] =
    L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\FreeAssetFilterTest";
inline constexpr const wchar_t* kUninstallKey =
    kTestMode ? kUninstallKeyTest : kUninstallKeyProd;

// 安装信息键下的值名（D11）。
inline constexpr wchar_t kValueInstallDir[] = L"InstallDir";
inline constexpr wchar_t kValueInstallLocation[] = L"InstallLocation";
inline constexpr wchar_t kValueOptDesktop[] = L"OptDesktop";
inline constexpr wchar_t kValueOptStartmenu[] = L"OptStartmenu";
inline constexpr wchar_t kValueOptAutostart[] = L"OptAutostart";
inline constexpr wchar_t kValueVersion[] = L"Version";

// ---------------------------------------------------------------------------
// 单实例互斥体（D2/C2：三个独立所有权，禁止共用）
// ---------------------------------------------------------------------------

// SetupMutex：NSIS setup 从 .onInit 持有到进程退出。
inline constexpr wchar_t kSetupMutexProd[] = L"Local\\FreeAssetFilterSetupMutex";
inline constexpr wchar_t kSetupMutexTest[] = L"Local\\FreeAssetFilterSetupMutex.Test";
inline constexpr const wchar_t* kSetupMutex =
    kTestMode ? kSetupMutexTest : kSetupMutexProd;

// MaintenanceMutex：C++ GUI 所有模式持有到窗口销毁，防止第二个 UI。
inline constexpr wchar_t kMaintenanceMutexProd[] = L"Local\\FreeAssetFilterMaintenanceMutex";
inline constexpr wchar_t kMaintenanceMutexTest[] = L"Local\\FreeAssetFilterMaintenanceMutex.Test";
inline constexpr const wchar_t* kMaintenanceMutex =
    kTestMode ? kMaintenanceMutexTest : kMaintenanceMutexProd;

// UninstallEngineMutex：NSIS 卸载 helper 从 un.onInit 持有到进程退出。
inline constexpr wchar_t kUninstallEngineMutexProd[] =
    L"Local\\FreeAssetFilterUninstallEngineMutex";
inline constexpr wchar_t kUninstallEngineMutexTest[] =
    L"Local\\FreeAssetFilterUninstallEngineMutex.Test";
inline constexpr const wchar_t* kUninstallEngineMutex =
    kTestMode ? kUninstallEngineMutexTest : kUninstallEngineMutexProd;

// ---------------------------------------------------------------------------
// 跨进程 INI 文件名（固定在安装目录；路径由双方按 installDir 推导，M4）
// ---------------------------------------------------------------------------

inline constexpr wchar_t kMaintenanceDecisionFile[] = L"maintenance-decision.ini";
inline constexpr wchar_t kUninstallRequestFile[] = L"uninstall-request.ini";
inline constexpr wchar_t kUninstallResultFile[] = L"uninstall-result.ini";

// INI 节名（D3/D5）。
inline constexpr wchar_t kMaintenanceSection[] = L"maintenance";
inline constexpr wchar_t kUninstallSection[] = L"uninstall";

// maintenance-decision.ini 键：schema 先写，action 最后写作为终端键（D3）。
inline constexpr wchar_t kKeySchema[] = L"schema";
inline constexpr wchar_t kKeyAction[] = L"action";
inline constexpr wchar_t kKeyPid[] = L"pid";
inline constexpr wchar_t kKeyAck[] = L"ack";

// uninstall-request.ini / uninstall-result.ini 键（D5/D15）。
inline constexpr wchar_t kKeyDeleteUserData[] = L"delete_user_data";
inline constexpr wchar_t kKeyUiPid[] = L"ui_pid";
inline constexpr wchar_t kKeyUiExe[] = L"ui_exe";
inline constexpr wchar_t kKeyCancelled[] = L"cancelled";
inline constexpr wchar_t kKeyUiDone[] = L"ui_done";
inline constexpr wchar_t kKeyStage[] = L"stage";
inline constexpr wchar_t kKeyPermille[] = L"permille";
inline constexpr wchar_t kKeyError[] = L"error";
inline constexpr wchar_t kKeyWarning[] = L"warning";
inline constexpr wchar_t kKeyDone[] = L"done";

// maintenance action 值（D3）。
inline constexpr wchar_t kActionRepair[] = L"repair";
inline constexpr wchar_t kActionUninstall[] = L"uninstall";
inline constexpr wchar_t kActionCancel[] = L"cancel";

// ---------------------------------------------------------------------------
// 安装目录内固定文件名（D10/C4；供 UI、进程匹配与卸载入口复用）
// ---------------------------------------------------------------------------

inline constexpr wchar_t kAppExeName[] = L"FreeAssetFilter.exe";
inline constexpr wchar_t kUninstallUiExeName[] = L"FreeAssetFilterUninstall.exe";
inline constexpr wchar_t kUninstallHelperExeName[] = L"UninstallHelper.exe";
inline constexpr wchar_t kLibwinpthreadDllName[] = L"libwinpthread-1.dll";
inline constexpr wchar_t kInternalDirName[] = L"_internal";

// 快捷方式词干（D13/F2 测试隔离的唯一事实来源）：
//   生产 = FreeAssetFilter：桌面 <Desktop>\FreeAssetFilter.lnk，开始菜单
//          <Programs>\FreeAssetFilter\FreeAssetFilter.lnk（同名文件夹）。
//   测试 = FreeAssetFilterTest：桌面 <Desktop>\FreeAssetFilterTest.lnk，开始菜单
//          <Programs>\FreeAssetFilterTest.lnk（扁平，不使用生产文件夹）。
// installer.nsi 不能 include 本头文件，必须同步维护
// !define SHORTCUT_STEM_PROD / SHORTCUT_STEM_TEST（见 installer.nsi）。
inline constexpr wchar_t kShortcutStemProd[] = L"FreeAssetFilter";
inline constexpr wchar_t kShortcutStemTest[] = L"FreeAssetFilterTest";
inline constexpr const wchar_t* kShortcutStem =
    kTestMode ? kShortcutStemTest : kShortcutStemProd;

// ---------------------------------------------------------------------------
// 卸载阶段（D5：顺序冻结；UI 只消费 helper 写入的真实阶段）
// ---------------------------------------------------------------------------

enum class UninstallStage {
    Started = 0,
    RemovingShortcuts,
    RemovingRegistry,
    RemovingFiles,
    RemovingUserData,
    Done,
    Failed,
    Cancelled,
};

// 与枚举一一对应的 INI `stage=` 值（D5）；禁止在其它 .cpp 重复这些字面量。
inline constexpr wchar_t kStageStarted[] = L"started";
inline constexpr wchar_t kStageRemovingShortcuts[] = L"removing_shortcuts";
inline constexpr wchar_t kStageRemovingRegistry[] = L"removing_registry";
inline constexpr wchar_t kStageRemovingFiles[] = L"removing_files";
inline constexpr wchar_t kStageRemovingUserData[] = L"removing_user_data";
inline constexpr wchar_t kStageDone[] = L"done";
inline constexpr wchar_t kStageFailed[] = L"failed";
inline constexpr wchar_t kStageCancelled[] = L"cancelled";

// ---------------------------------------------------------------------------
// 默认超时（毫秒；D15 C1/C2、M2、H5）
// ---------------------------------------------------------------------------

// setup 等待 maintenance-decision.ini 的 action 终键：30 分钟。
inline constexpr std::uint32_t kDecisionTimeoutMs = 30u * 60u * 1000u;
// helper 等待 uninstall-request.ini（仅在 UI 进程存活时）：30 分钟。
inline constexpr std::uint32_t kRequestTimeoutMs = 30u * 60u * 1000u;
// maintenance 卸载等待 setup 写 ack=1：10 秒。
inline constexpr std::uint32_t kAckTimeoutMs = 10u * 1000u;
// helper 写完 done=1 后轮询 ui_done：60 秒（M2/C1）。
inline constexpr std::uint32_t kUiDoneWaitMs = 60u * 1000u;
// ui_done=1 后等待 UI 进程退出：10 秒（M2/C1）。
inline constexpr std::uint32_t kUiProcessWaitMs = 10u * 1000u;
// helper 等待 SetupMutex 释放：15 秒（C2）。
inline constexpr std::uint32_t kSetupMutexWaitMs = 15u * 1000u;
// setup 检测 GUI 是否出现窗口：10 秒（H5）。
inline constexpr std::uint32_t kGuiWindowDetectMs = 10u * 1000u;
// 跨进程轮询间隔：200 毫秒（D3/M4/H5）。
inline constexpr std::uint32_t kPollIntervalMs = 200u;

}  // namespace faf::protocol
