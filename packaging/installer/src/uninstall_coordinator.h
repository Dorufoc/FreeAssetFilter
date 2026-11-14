#pragma once
//
// uninstall_coordinator.h - 卸载流程的 UI 侧协调器（计划 T12 / D15 C1、C4）。
//
// 职责边界：
//   * 写 uninstall-request.ini（**必须先于启动 helper**，D5/T12）；
//   * helperPid==0 时启动 `<installDir>\UninstallHelper.exe /uninstall-helper
//     /installdir "<installDir>"`；helperPid!=0（helper 先启动、UI 后启动）时
//     只附着该 PID 做可选的提前退出探测，绝不二次启动 helper（D15 C4）；
//   * 工作线程轮询 uninstall-result.ini，把真实 stage/permille 与终端阶段通过
//     WM_UNINSTALL_PROGRESS / WM_UNINSTALL_DONE 投递给 UI 线程；
//   * 绝不删除文件/注册表/快捷方式/用户数据——删除只属于 NSIS helper。
//
// 终端规则（D15 C1）：done=1 是唯一完成信号；只有 done=1 && stage 为
// done/failed/cancelled 才投递 WM_UNINSTALL_DONE。文件存在、helper 退出都不能
// 单独当作完成。warning 不参与终态判定。
//
#include <windows.h>

#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>

#include "render/maintenance_protocol.h"  // protocol::UninstallStage / kUninstallHelperExeName

namespace spk {

class UninstallCoordinator {
public:
    // installDir    : 安装目录（helper exe 与 request/result 的父目录）
    // deleteUserData: 用户在确认页选择的 delete_user_data
    // uiPid         : 当前 UI 进程 PID（写入 request 的 ui_pid）
    // helperPid     : 0 = 由本对象启动 helper；非 0 = helper 已存在，只附着探测
    // requestPath   : uninstall-request.ini 绝对路径
    // resultPath    : uninstall-result.ini 绝对路径
    // notifyWnd     : 接收 WM_UNINSTALL_* 的 UI 窗口（消息在 UI 线程处理）
    UninstallCoordinator(std::wstring installDir, bool deleteUserData, DWORD uiPid,
                         DWORD helperPid, std::wstring requestPath, std::wstring resultPath,
                         HWND notifyWnd);
    ~UninstallCoordinator();

    UninstallCoordinator(const UninstallCoordinator&) = delete;
    UninstallCoordinator& operator=(const UninstallCoordinator&) = delete;

    // 写 request（失败则不启动 helper）→ 启动/附着 helper → 创建轮询线程。
    // 失败时通过 error 返回可直接展示的原因；成功返回 true（终态由消息投递）。
    bool Start(std::wstring* error);

    // Finish(Uninstall) 关闭：向已存在的 request 追加 ui_done=1（幂等）。
    // helper 依赖它确认 UI 已同意卸载收尾；request 不存在/写失败返回 false。
    bool WriteUiDone();

    // 是否已因启动失败/helper 提前退出/超时进入失败态（线程安全）。
    bool Failed() const;
    // 失败原因（helper 在 result 中写的 error，或本对象的探测错误）。
    std::wstring Error() const;
    // 终态结果中的 warning（线程安全）；仅作 Finish 页非终端提示，不改变终态。
    std::wstring Warning() const;

private:
    static DWORD WINAPI ThreadProc(LPVOID param);
    void Worker();
    bool LaunchHelper(std::wstring* error);
    bool TryReadTerminal();  // 读到 done=1 的终态时投递 WM_UNINSTALL_DONE
    void PostTerminal(protocol::UninstallStage stage);
    void SetFailed(std::wstring error);
    void SetWarning(std::wstring warning);

    std::wstring installDir_;
    std::wstring requestPath_;
    std::wstring resultPath_;
    bool deleteUserData_{false};
    DWORD uiPid_{0};
    DWORD helperPid_{0};
    HWND notifyWnd_{nullptr};

    HANDLE helperProcess_{nullptr};  // 仅用于提前退出探测；不终止 helper
    HANDLE stopEvent_{nullptr};
    HANDLE thread_{nullptr};

    std::atomic<bool> started_{false};
    std::atomic<bool> stop_{false};
    std::atomic<bool> failed_{false};
    std::atomic<bool> uiDoneWritten_{false};
    // Start 先建 worker、后启动 helper；worker 在此标记前不读取 result，
    // 防止上一次残留的 done=1 被误当成本次终态而提前关闭 UI。
    std::atomic<bool> helperReady_{false};

    mutable std::mutex errorMutex_;
    std::wstring error_;
    mutable std::mutex warningMutex_;
    std::wstring warning_;
};

}  // namespace spk
