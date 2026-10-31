#pragma once
//
// install_engine.h - 安装引擎（Todo 13，Wave 4）。
//
// 职责（Frozen contracts §11 / §3 / §10 / §1，不得另行发明）：
//   1) §11：**先**等待 payload 就绪哨兵（`payload.parent_path() / "payload.ready"`，
//      无父目录如 "." 时退化为当前目录下 `payload.ready`）；超时生产默认 1500000ms
//      （严格小于 NSIS `SPK_WAIT_TIMEOUT_MS`=1800000ms），环境变量
//      `SPK_PAYLOAD_TIMEOUT_MS` **无条件**覆盖（不依赖 SPK_TESTMODE）；
//      超时才写 `abort=1 error=payload-timeout` 并退出。
//   2) **再**递归预扫描 payload 总字节与文件数（哨兵在 payload 目录之外，绝不计数）。
//   3) 复制时按真实已写字节产出 **permille 0..1000**（§10）经回调上报；大文件经
//      CopyFileExW 分块推进进度（不再只在整文件完成后上报一次）；支持取消
//      （§3：分块回调中止复制 + 删除本次运行已写入的文件 + 写 `abort=1`）。
//   4) §1：结果为 INI（`WritePrivateProfileStringW` W 变体、UTF-16LE + BOM、
//      `[spk]` 占位节先写使 `[install]` 永不为首节、`abort` 最后写为终端键、
//      无 `launch` 键）。**本文件是结果 INI 的唯一写作者**——任何其它模块不得另立写法。
//   5) T6/D4/D15-H1：`InstallMode::Repair` 失败/取消不回滚已写文件；复制与清旧跳过
//      用户数据子树（`data`、`_internal\data`）；预扫描后、首次写入前若可用空间
//      小于 payloadBytes×1.1，写 `abort=1 error=repair-no-space` 且不写安装目录。
//
// 本引擎无 HWND / COM 依赖（仅 Win32 INI/文件 API + std::filesystem），可在无窗口
// harness 中直接驱动；进度经回调、取消经 `std::atomic<bool>` 传入。
//
#include <atomic>
#include <cstdint>
#include <filesystem>
#include <functional>
#include <string>
#include <vector>

namespace spk {

// 安装选项（§2 默认值由 app_state.h / InstallerWindow 提供；此处仅承载传递）。
struct InstallOptions {
    bool desktop = true;
    bool startmenu = true;
    bool autostart = false;
};

// 引擎运行模式（T6/D4）。Fresh = 既有安装/重装语义（失败清理本次写入）；
// Repair = 修复覆盖（失败/取消不回滚、保留已写文件）。模式不写入结果 INI。
enum class InstallMode {
    Fresh,
    Repair,
};

// 引擎一次运行的完整结果（同时用于 harness 断言与窗口侧收尾）。
struct InstallResult {
    InstallMode mode = InstallMode::Fresh;  // 诊断用；不写入 INI
    bool ok = false;          // 复制全部成功
    bool cancelled = false;   // 用户取消（§3）
    bool timedOut = false;    // 哨兵等待超时（§11）
    bool iniWritten = false;  // 结果 INI 写入成功
    std::wstring error;       // 失败/取消原因；成功为空串
    std::uint64_t totalFiles = 0;   // 预扫描：payload 文件数（不含哨兵；Repair 已剔除用户数据）
    std::uint64_t totalBytes = 0;   // 预扫描：payload 总字节（Repair 为实际复制集合字节）
    std::uint64_t copiedFiles = 0;  // 已写文件数（清理前）
    std::uint64_t copiedBytes = 0;  // 已写字节数（清理前）
};

// §1 唯一结果 INI 写作者（W 变体）。UTF-16LE + BOM 预创建**仅发生在本函数内**
// （严禁在 GUI 启动或开始安装时预创建）。写入顺序：
//   [spk] schema=1（占位节，使 [install] 非首节）
//   → [install] dir / desktop / startmenu / autostart / error
//   → 终端键 abort（恒写、最后写）
//   → 防御性 flush `WritePrivateProfileStringW(nullptr,nullptr,nullptr,path)`。
// 成功返回 true。**无 launch 键**（§15）。
bool WriteInstallResultIni(const std::wstring& resultPath, const std::wstring& dir, bool abort,
                           const std::wstring& error, const InstallOptions& options);

// §11 冻结的哨兵路径推导：`path(payload).parent_path() / "payload.ready"`；
// 无父目录（默认 "."）⇒ 当前目录下 `payload.ready`。
std::filesystem::path PayloadSentinelPath(const std::filesystem::path& payload);

// §11 超时（ms）：无条件读环境变量 `SPK_PAYLOAD_TIMEOUT_MS`；未设置/非法 ⇒ 生产默认
// 1500000（严格小于 NSIS SPK_WAIT_TIMEOUT_MS=1800000）。
std::uint64_t PayloadTimeoutMs();

class InstallEngine {
public:
    // 复制大文件时经 CopyFileExW 分块回调，permille 变化时上报（0..1000 整数）；
    // 每个文件结束后仍按累计字节上报一次，成功收尾时恒回调 1000。
    // PostMessage 的 ~30fps 节流由调用方（InstallerWindow）负责；本回调不节流。
    using ProgressFn = std::function<void(int permille)>;

    // payloadTimeoutMs = 0 ⇒ 使用 PayloadTimeoutMs()（环境变量/默认 1500000）。
    InstallEngine(std::wstring payload, std::wstring installDir, std::wstring resultPath,
                  std::uint64_t payloadTimeoutMs = 0);

    // 兼容入口（既有调用方）：等价于 Run(options, InstallMode::Fresh, cancel, onProgress)。
    InstallResult Run(const InstallOptions& options, const std::atomic<bool>& cancel,
                      const ProgressFn& onProgress);

    // 同步执行（由安装/修复线程调用）。cancel 为取消信号（§3）。返回完整结果，
    // 结果 INI 已在内部（唯一写入器）写好。Fresh 语义与既有行为完全一致。
    InstallResult Run(const InstallOptions& options, InstallMode mode,
                      const std::atomic<bool>& cancel, const ProgressFn& onProgress);

    // permille = written*1000/total（total==0 ⇒ 1000）；钳制 0..1000。纯函数，便于断言。
    static int PermilleFor(std::uint64_t written, std::uint64_t total);

private:
    struct Entry {
        std::filesystem::path source;    // payload 内绝对/原始路径
        std::filesystem::path relative;  // 相对 payload 的路径（复制到 target 时拼接）
        std::uint64_t size = 0;
    };

    // 失败/取消收尾：Fresh 清理本次写入（文件 + 本次创建的空目录）；Repair 不清理；
    // 两者均按 §1 写结果 INI（Repair 的 error 统一加 `repair-` 前缀）。
    InstallResult Finalize(InstallResult result, const InstallOptions& options);
    // §3：删除本次运行写入的文件（含被覆盖文件——已知取舍），再按深度逆序删除本次创建的空目录。
    void CleanupWritten();
    // 修复成功后的清旧：仅扫描 `_internal`，删除不在新 payload 清单中的文件；
    // `_internal\data` 整棵子树跳过，`$INSTDIR\data` 不在扫描范围内（D15 H1）。
    void RemoveStaleInternalFiles(const std::filesystem::path& targetRoot,
                                  const std::vector<Entry>& copied) const;
    // 确保父目录存在；记录本次创建的目录链（供清理）。
    bool EnsureParentCreated(const std::filesystem::path& parent);

    std::wstring payload_;
    std::wstring installDir_;
    std::wstring resultPath_;
    std::uint64_t payloadTimeoutMs_ = 0;  // 0 ⇒ PayloadTimeoutMs()

    std::vector<std::filesystem::path> writtenFiles_;  // 本次运行写入的文件（逆序删除）
    std::vector<std::filesystem::path> createdDirs_;   // 本次运行创建的目录（逆序删除）
};

}  // namespace spk
