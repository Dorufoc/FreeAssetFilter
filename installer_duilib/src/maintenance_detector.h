#pragma once
//
// maintenance_detector.h - 维护/修复前的只读安装探测（T2）。
//
// 契约来源：计划 T2 / D11 / D13 / D15-H1；常量统一取自
// `render/maintenance_protocol.h`（生产/测试键由 kTestMode 在编译期决定）。
//
//   detected         : installDir\FreeAssetFilter.exe 存在 || installDir\_internal 存在
//   complete         : 两者都存在（程序文件完整）
//   version          : FreeAssetFilter.exe 的 StringFileInfo\...\FileVersion；
//                      任何一步失败（exe 不存在、无版本资源、无该字符串）=> 空串
//   optDesktop       : 优先 HKCU 安装信息键 OptDesktop (DWORD)；
//                      缺失/类型或长度非法时按桌面快捷方式是否存在推断；
//                      无法定位桌面目录时回退 true
//   optStartmenu     : 同上，按开始菜单快捷方式推断，回退 true
//   optAutostart     : 同上，按 HKCU\...\Run 值是否精确指向本安装 exe 推断，
//                      无法推断时回退 false
//   optionsInferred  : 至少一项选项来自推断（而非注册表 DWORD）
//
// 只读约束：本模块仅使用 GetFileAttributesW / 版本资源查询 /
// RegOpenKeyExW(KEY_QUERY_VALUE) + RegQueryValueExW / SHGetKnownFolderPath。
// 不创建目录、不写注册表、不写文件；唯一的写操作是显式调用的
// WriteMaintenanceDump（/test-dump-maintenance 诊断）。
//
#include <string>

namespace faf {

struct MaintenanceInfo {
    bool detected = false;
    bool complete = false;
    std::wstring installDir;
    std::wstring version;
    bool optDesktop = true;
    bool optStartmenu = true;
    bool optAutostart = false;
    bool optionsInferred = false;
};

// 只读探测。installDir 允许带尾部反斜杠/正斜杠或外层引号；为空时回退读取
// 安装信息键的 InstallDir (SZ)。所有失败路径返回稳定默认值，不抛异常。
MaintenanceInfo Detect(const std::wstring& installDir);

// `/test-dump-maintenance=<path>` 的 INI 诊断输出（本模块唯一允许的写操作）。
// 以 UTF-16LE + BOM 覆盖写入；节 [maintenance]，键：
//   schema=1
//   detected=0|1   complete=0|1
//   install_dir=<路径>   version=<FileVersion 或空>
//   opt_desktop=0|1   opt_startmenu=0|1   opt_autostart=0|1
//   options_inferred=0|1
// 父目录必须已存在（本函数不创建目录）。成功返回 true。
bool WriteMaintenanceDump(const MaintenanceInfo& info, const std::wstring& iniPath);

}  // namespace faf
