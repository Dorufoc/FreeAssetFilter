#pragma once
//
// uninstall_protocol.h - 维护/卸载跨进程 INI 协议（T5，C++ 侧）。
//
// 契约来源：计划 D3 / D5 / D15 C1、C3、C4、M2、M4，以及 T5 的验收条目。
// 所有节名、键名、值、阶段枚举与超时值都取自 render/maintenance_protocol.h；
// 本模块不硬编码安装目录，所有路径由调用方按 installDir 推导后传入。
//
// 编码与刷盘（M4）：
//   - request/cancel/decision 的快照写函数在第一次 WritePrivateProfileStringW
//     之前先用 UTF-16LE BOM 预创建目标文件（CREATE_ALWAYS），保证 W 变体不会
//     退化成 ANSI 文件；WriteUiDone/WriteMaintenanceAck 只追加到已存在文件。
//   - 每次跨进程 WritePrivateProfileStringW 之后立即调用
//     WritePrivateProfileStringW(nullptr, nullptr, nullptr, path) 刷盘。
//     写序列内部的键顺序是协议的一部分（schema 先、终端键最后）。
//
// 就绪判定（只认终端键，绝不把“文件存在”当作完成）：
//   - request：schema=1 且（cancelled=1，或 delete_user_data/ui_pid/ui_exe 齐全）；
//   - result：done=1 且 stage 为 done/failed/cancelled 之一；
//   - decision：action 是终端键（由本模块最后写）；ack 由 setup 写、GUI 轮询。
//
// 读函数对“文件已存在但内容尚未写全”的情况在 200ms 窗口内重试；文件不存在时
// 立即返回 false。所有输出参数允许传 nullptr。
//
#include <windows.h>

#include <cstdint>
#include <string>

#include "render/app_state.h"             // MaintenanceAction
#include "render/maintenance_protocol.h"  // UninstallStage / protocol::* 常量

namespace faf {

using protocol::UninstallStage;

// D5/T17 阶段进度映射：started=0 → shortcuts=100 → registry=300 → files=600
// → user_data=800 → done=1000。这四个移除阶段加 done 正好对应协议文档中的
// 100/300/600/800/1000；failed/cancelled 不是成功终态，返回 0。纯函数。
int StageToPermille(UninstallStage stage);

// 写 uninstall-request.ini（UI → helper）。顺序：schema=1 → delete_user_data →
// ui_pid → ui_exe（最后写，作为读侧的就绪信号）。不写 ui_done，也不写
// request_path/result_path（路径由双方按 installDir 推导）。
bool WriteUninstallRequest(const std::wstring& path, bool deleteUserData, DWORD uiPid,
                           const std::wstring& uiExe);

// 写“UI 在确认页取消”的 request：schema=1 → cancelled=1。helper 读到后必须
// 不删除任何文件。会覆盖目标文件中的旧 request 内容。
bool WriteUninstallCancel(const std::wstring& path);

// helper 读 request。缺失返回 false；部分写入在 200ms 内重试。cancelled=1 时
// 只保证 cancelled 输出为 true，其余字段保持默认值。
bool ReadUninstallRequest(const std::wstring& path, bool* deleteUserData, DWORD* uiPid,
                          std::wstring* uiExe, bool* cancelled);

// UI 在 Finish(Uninstall) 关闭时把 ui_done=1 追加到已有 request；文件不存在或
// 写入失败返回 false（不预创建，避免伪造一个不完整的 request）。
bool WriteUiDone(const std::wstring& path);

// UI 读 uninstall-result.ini。done 是唯一终端键：done=1 且 stage 为
// done/failed/cancelled 时才返回 true；stage=failed 时 error 一并返回；
// warning 只用于 done 之后的清理告警，不改变终态。部分写入在 200ms 内重试。
bool ReadUninstallResult(const std::wstring& path, UninstallStage* stage, int* permille,
                         bool* done, std::wstring* error, std::wstring* warning);

// T12：只读当前 stage/permille（不要求 done=1），供 UI 在卸载进行中显示真实阶段。
// 文件不存在或 stage 尚未写入时返回 false；不改变 ReadUninstallResult 的终端语义。
bool ReadUninstallProgress(const std::wstring& path, UninstallStage* stage, int* permille);

// maintenance 卸载：轮询 maintenance-decision.ini 的 ack=1，最多 timeoutMs
// （默认 protocol::kAckTimeoutMs = 10000）。文件暂时不存在也继续等待。
bool WaitForDecisionAck(const std::wstring& decisionPath,
                        std::uint32_t timeoutMs = protocol::kAckTimeoutMs);

// 写维护决定。顺序：schema=1 → pid → ack=0 → action（最后写，终端键）。
// action 只会是 protocol 中的 repair/uninstall/cancel。
bool WriteMaintenanceDecision(const std::wstring& path, MaintenanceAction action, DWORD pid);

// setup 侧/诊断用：在已有 decision 文件上写 ack=1。文件不存在返回 false。
bool WriteMaintenanceAck(const std::wstring& path);

}  // namespace faf
