#pragma once
//
// app_state.h - 安装器共享状态（Frozen contract §12 的唯一作者 = Todo 2）。
//
// 页面枚举与选项字段集中定义于此；Todo 9-12 只消费该结构，不得各自另定义
// 页面枚举或选项字段。默认值遵循 Frozen contract §2：
// 桌面=1、开始菜单=1、开机自启=0、完成后启动=1。
//
#include <string>

enum Page {
    Welcome = 0,
    License,
    Location,
    Options,
    Progress,
    Finish,
};

struct AppState {
    int page = Welcome;
    bool agreed = false;
    std::wstring installDir;
    bool optDesktop = true;    // §2 默认 1
    bool optStartmenu = true;  // §2 默认 1
    bool optAutostart = false; // §2 默认 0
    bool optLaunch = true;     // §2 默认 1
};
