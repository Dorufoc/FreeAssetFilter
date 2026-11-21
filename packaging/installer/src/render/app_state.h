#pragma once
//
// app_state.h - 安装器共享状态（Frozen contract §12 的唯一作者 = Todo 2）。
//
// 页面枚举与选项字段集中定义于此；Todo 9-12 只消费该结构，不得各自另定义
// 页面枚举或选项字段。默认值遵循 Frozen contract §2：
// 桌面=1、开始菜单=1、开机自启=0、完成后启动=1。
//
#include <string>

// 追加需求（2026-10-18）：5 页 —— Welcome / License / Configure / Progress / Finish。
// 顺序冻结（installer_window 的页面接线依赖此顺序）。
// License 仅由配置页的协议链接进入；页面编号保持稳定。
// 维护/卸载需求（T1）：只允许追加到末尾，禁止重排 0..4 的原编号。
enum Page {
    Welcome = 0,
    License,   // 两份协议共用的独立阅读页
    Configure,
    Progress,
    Finish,
    Maintenance = 5,       // 维护页（修复 / 卸载 / 取消）
    UninstallConfirm = 6,  // 卸载确认页
    Message = 7,           // 通用消息/错误页
    UninstallChecklist = 8,
};

enum class MaintenanceOffer { Repair, Update, UninstallOnly };


// 本次 UI 会话的操作类型（D6：Progress/Finish 通过 operation 复用）。
enum class Operation {
    Install,
    Repair,
    Uninstall,
    Update,
};

// 维护页用户的最终动作（D3 handoff：repair|uninstall|cancel）。
enum class MaintenanceAction {
    Repair,
    Uninstall,
    Cancel,
    Update,
};

// 启动模式（D1，由 main.cpp 解析命令行后传入窗口）。
enum class AppMode {
    Install,
    Maintenance,
    Uninstall,
};

struct AppState {
    int page = Welcome;
    bool agreed = false;
    std::wstring installDir;
    bool optDesktop = true;    // §2 默认 1
    bool optStartmenu = true;  // §2 默认 1（新版设计稿无勾选项：始终创建）
    bool optAutostart = false; // §2 默认 0
    bool optLaunch = true;     // §2 默认 1（完成页「立即体验」承担）
    // 2026-11 设计稿新增：「添加到右键菜单」（默认开）。写入 install-result.ini 的
    // `ctxmenu=0|1`，由 NSIS Section Install 落成 HKLM 的 Directory\shell / *\shell。
    bool optContextMenu = true;

    // 维护/卸载扩展字段（T1）；不得改变上方安装 5 页字段的默认行为。
    Operation operation = Operation::Install;
    bool deleteUserData = false;       // 卸载确认页复选框，默认不删用户数据
    bool optLaunchAfterRepair = false; // 修复完成页“立即启动”，默认 false
    std::wstring installedVersion;     // MaintenanceDetector 读取的已安装版本（失败为空）
    bool installDetected = false;      // 已安装判定结果（exe 或 _internal 存在）
    bool setupExited = false;          // /setup-pid 监视到 setup 提前退出
};
