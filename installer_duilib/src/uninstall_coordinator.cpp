//
// uninstall_coordinator.cpp - 卸载流程 UI 侧协调器实现（T12）。
//
// 线程模型与 InstallerWindow::InstallThread/CloseAppThread 一致：
//   * UI 线程独占页面状态，工作线程只读 INI、探测 helper 进程并 PostMessageW；
//   * 工作线程不触碰窗口/COM，也不删除任何文件；
//   * 对象析构时置停止事件并等待线程退出，避免 worker 使用已销毁的 this。
//
#include "uninstall_coordinator.h"

#include <windows.h>

#include <utility>

#include "render/messages.h"     // WM_UNINSTALL_PROGRESS / WM_UNINSTALL_DONE
#include "uninstall_protocol.h"  // WriteUninstallRequest / ReadUninstallProgress / ...

namespace faf {
namespace {

// UI 侧必须比 helper 的 request 等待更久：helper 写完 done=1 后还会等待
// ui_done（kUiDoneWaitMs）。若两者相同，UI 可能先投递 Failed，随后用户关闭
// Finish 又写 ui_done，形成 Failed/Cancelled 竞争；额外留出该等待窗口。
constexpr ULONGLONG kResultTimeoutMs =
    static_cast<ULONGLONG>(protocol::kRequestTimeoutMs) + protocol::kUiDoneWaitMs;

bool IsTerminalStage(protocol::UninstallStage stage) {
    return stage == protocol::UninstallStage::Done ||
           stage == protocol::UninstallStage::Failed ||
           stage == protocol::UninstallStage::Cancelled;
}

}  // namespace

UninstallCoordinator::UninstallCoordinator(std::wstring installDir, bool deleteUserData,
                                           DWORD uiPid, DWORD helperPid,
                                           std::wstring requestPath, std::wstring resultPath,
                                           HWND notifyWnd)
    : installDir_(std::move(installDir)),
      requestPath_(std::move(requestPath)),
      resultPath_(std::move(resultPath)),
      deleteUserData_(deleteUserData),
      uiPid_(uiPid),
      helperPid_(helperPid),
      notifyWnd_(notifyWnd) {}

UninstallCoordinator::~UninstallCoordinator() {
    // 先唤醒轮询线程：Worker 的每个等待点都带超时，正常会在 200ms 内退出。
    // 使用 Win32 线程句柄 + 显式 Wait（而不是 std::thread 析构），避免 terminate。
    stop_.store(true);
    if (stopEvent_) SetEvent(stopEvent_);
    if (thread_) {
        WaitForSingleObject(thread_, INFINITE);
        CloseHandle(thread_);
        thread_ = nullptr;
    }
    if (stopEvent_) {
        CloseHandle(stopEvent_);
        stopEvent_ = nullptr;
    }
    if (helperProcess_) {
        // 只关闭探测句柄，绝不终止 helper（D15 C1/C4）。
        CloseHandle(helperProcess_);
        helperProcess_ = nullptr;
    }
}

bool UninstallCoordinator::Start(std::wstring* error) {
    const auto fail = [&](const std::wstring& text) {
        SetFailed(text);
        if (error) *error = text;
        return false;
    };

    if (started_.exchange(true)) return fail(L"卸载协调器已经启动。");
    if (!notifyWnd_ || !IsWindow(notifyWnd_)) return fail(L"卸载窗口无效，无法开始卸载。");
    if (installDir_.empty()) return fail(L"安装目录为空，无法开始卸载。");
    if (requestPath_.empty() || resultPath_.empty()) {
        return fail(L"卸载请求或结果文件路径为空，无法开始卸载。");
    }

    // D5/T12：必须先写 request，再启动 helper（helper 启动后会立刻读取它）。
    wchar_t exePath[32768] = {};
    const DWORD exeLen = GetModuleFileNameW(nullptr, exePath, ARRAYSIZE(exePath));
    if (exeLen == 0 || exeLen >= ARRAYSIZE(exePath)) {
        return fail(L"无法获取当前卸载程序路径。");
    }
    if (!faf::WriteUninstallRequest(requestPath_, deleteUserData_, uiPid_, exePath)) {
        return fail(L"无法写入卸载请求文件：" + requestPath_);
    }

    // 缺陷 A：先建 stopEvent/worker，再启动 helper。这样 helper 启动失败时
    // worker 一定可被停止并 join，不会留下无主轮询线程；request 仍先于 helper。
    stopEvent_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!stopEvent_) return fail(L"无法创建卸载协调事件。");
    thread_ = CreateThread(nullptr, 0, ThreadProc, this, 0, nullptr);
    if (!thread_) {
        CloseHandle(stopEvent_);
        stopEvent_ = nullptr;
        return fail(L"无法创建卸载协调线程。");
    }

    if (helperPid_ == 0) {
        std::wstring launchError;
        if (!LaunchHelper(&launchError)) {
            // helper 未产生进程句柄；停止并 join 已启动的 worker 后干净返回。
            stop_.store(true);
            SetEvent(stopEvent_);
            WaitForSingleObject(thread_, INFINITE);
            CloseHandle(thread_);
            thread_ = nullptr;
            CloseHandle(stopEvent_);
            stopEvent_ = nullptr;
            return fail(launchError);
        }
    } else {
        // helper 先启动、UI 后启动：只附着已有 PID 做提前退出探测，绝不二次启动。
        // OpenProcess 失败不阻断流程——result 仍可能已经写好或即将写好。
        helperProcess_ = OpenProcess(SYNCHRONIZE, FALSE, helperPid_);
    }
    // helper 已启动/附着后再放行 worker 读 result，避免上一次残留的 done=1
    // 被误当成本次终态（worker 在 Start 返回前已经开始轮询）。
    helperReady_.store(true);
    return true;
}

bool UninstallCoordinator::WriteUiDone() {
    if (requestPath_.empty()) return false;
    if (uiDoneWritten_.load()) return true;
    // 显式 faf:: 限定：成员函数名与协议函数同名，避免被名字查找遮蔽。
    if (!faf::WriteUiDone(requestPath_)) return false;
    uiDoneWritten_.store(true);
    return true;
}

bool UninstallCoordinator::Failed() const { return failed_.load(); }

std::wstring UninstallCoordinator::Error() const {
    std::lock_guard<std::mutex> lock(errorMutex_);
    return error_;
}

std::wstring UninstallCoordinator::Warning() const {
    std::lock_guard<std::mutex> lock(warningMutex_);
    return warning_;
}

DWORD WINAPI UninstallCoordinator::ThreadProc(LPVOID param) {
    static_cast<UninstallCoordinator*>(param)->Worker();
    return 0;
}

void UninstallCoordinator::Worker() {
    const ULONGLONG startTick = GetTickCount64();
    // 初值让 Started/0 也会投递一次（UI 可用作“helper 已开始”的确认）。
    protocol::UninstallStage lastStage = protocol::UninstallStage::Started;
    int lastPermille = -1;

    for (;;) {
        if (stop_.load()) return;
        if (WaitForSingleObject(stopEvent_, 0) == WAIT_OBJECT_0) return;

        // Start 先建 worker 后启动 helper；helper 就绪前不读 result，避免旧文件
        // 中残留的 done=1 被误判为本次卸载终态。
        if (!helperReady_.load()) {
            WaitForSingleObject(stopEvent_, protocol::kPollIntervalMs);
            continue;
        }

        protocol::UninstallStage stage = protocol::UninstallStage::Started;
        int permille = 0;
        const bool haveProgress = ReadUninstallProgress(resultPath_, &stage, &permille);
        if (haveProgress) {
            if (IsTerminalStage(stage)) {
                // stage 到达终态后还要等 done=1；ReadUninstallResult 的 200ms
                // 重试窗口用于覆盖 helper “先写 stage 再写 done”的时序。
                if (TryReadTerminal()) return;
            } else if (stage != lastStage || permille != lastPermille) {
                PostMessageW(notifyWnd_, WM_UNINSTALL_PROGRESS,
                             static_cast<WPARAM>(permille),
                             static_cast<LPARAM>(static_cast<int>(stage)));
                lastStage = stage;
                lastPermille = permille;
            }
        }

        // helper 提前退出：先做最后一次终态读取（helper 可能刚写完 done 就退出），
        // 仍读不到才按失败收口。绝不根据“进程没了”推断卸载成功。
        if (helperProcess_ && WaitForSingleObject(helperProcess_, 0) == WAIT_OBJECT_0) {
            if (TryReadTerminal()) return;
            DWORD exitCode = 0;
            GetExitCodeProcess(helperProcess_, &exitCode);
            SetFailed(L"卸载程序在完成前退出（代码 " + std::to_wstring(exitCode) + L"）。");
            PostTerminal(protocol::UninstallStage::Failed);
            return;
        }

        if (GetTickCount64() - startTick >= kResultTimeoutMs) {
            SetFailed(L"等待卸载结果超时。");
            PostTerminal(protocol::UninstallStage::Failed);
            return;
        }

        WaitForSingleObject(stopEvent_, protocol::kPollIntervalMs);
    }
}

bool UninstallCoordinator::LaunchHelper(std::wstring* error) {
    const std::wstring helperExe =
        installDir_ + L"\\" + protocol::kUninstallHelperExeName;
    // NSIS helper 与 UI 使用同一 installDir 作为工作目录；request 已经写好。
    std::wstring command = L"\"" + helperExe + L"\" /uninstall-helper /installdir \"" +
                           installDir_ + L"\"";

    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(helperExe.c_str(), command.data(), nullptr, nullptr, FALSE, 0, nullptr,
                        installDir_.c_str(), &startup, &process)) {
        if (error) {
            *error = L"无法启动卸载程序（错误码 " + std::to_wstring(GetLastError()) + L"）。";
        }
        return false;
    }
    helperProcess_ = process.hProcess;  // 只用于提前退出探测
    CloseHandle(process.hThread);
    return true;
}

bool UninstallCoordinator::TryReadTerminal() {
    protocol::UninstallStage stage = protocol::UninstallStage::Started;
    int permille = 0;
    bool done = false;
    std::wstring error;
    std::wstring warning;
    if (!ReadUninstallResult(resultPath_, &stage, &permille, &done, &error, &warning) || !done) {
        return false;  // 只有 done=1 才是完成；warning 不参与终态
    }
    if (!IsTerminalStage(stage)) return false;

    // warning 只做 Finish 页非终端提示，绝不参与终态判定。
    SetWarning(warning);
    if (stage == protocol::UninstallStage::Failed) {
        SetFailed(error.empty() ? L"卸载程序报告失败。" : error);
    }
    PostTerminal(stage);
    return true;
}

void UninstallCoordinator::PostTerminal(protocol::UninstallStage stage) {
    PostMessageW(notifyWnd_, WM_UNINSTALL_DONE, static_cast<WPARAM>(stage), 0);
}

void UninstallCoordinator::SetFailed(std::wstring error) {
    {
        std::lock_guard<std::mutex> lock(errorMutex_);
        error_ = std::move(error);
    }
    failed_.store(true);
}

void UninstallCoordinator::SetWarning(std::wstring warning) {
    std::lock_guard<std::mutex> lock(warningMutex_);
    warning_ = std::move(warning);
}

}  // namespace faf
