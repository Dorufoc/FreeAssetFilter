#pragma once
#include <windows.h>
// wParam carries progress in PERMILLE (0..1000), NOT 0..100.
constexpr UINT WM_INSTALL_PROGRESS = WM_APP + 1; // wParam = permille 0..1000
constexpr UINT WM_INSTALL_DONE     = WM_APP + 2; // wParam = result code
constexpr UINT WM_UI_TICK          = WM_APP + 3; // animation frame

// 维护/卸载消息（T1，值冻结；现有 3 个值保持不变）。
// WM_UNINSTALL_PROGRESS: wParam = permille 0..1000（helper 写入的真实阶段进度），
//   lParam = spk::protocol::UninstallStage（当前阶段，供 UI 映射中文文案，D5/T12）。
constexpr UINT WM_UNINSTALL_PROGRESS = WM_APP + 4;
// WM_UNINSTALL_DONE: wParam = 终端 UninstallStage（Done / Failed / Cancelled），
//   lParam = 0；UI 仅在 done=1 时据此分流 Finish / Message（D15 C1）。
constexpr UINT WM_UNINSTALL_DONE = WM_APP + 5;
// WM_APP_CLOSE_DONE: wParam = 1 表示已安装应用已关闭，0 表示关闭失败（D9）。
constexpr UINT WM_APP_CLOSE_DONE = WM_APP + 6;
// WM_SPK_ACTIVATE: 无载荷；第二实例请求已有窗口恢复并置前（D2/T13）。
constexpr UINT WM_SPK_ACTIVATE = WM_APP + 7;
