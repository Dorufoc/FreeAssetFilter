# Sopeek 安装器（D2D1 + DirectComposition / WinUI3 风格）

该目录是 Sopeek 安装器（C++ GUI + NSIS 封装）的工程目录。GUI 是一个自研 C++ Win32 程序：
无边框窗口 + DirectComposition 合成 + Win11 Mica 背景，固定 900×600 DIP（逻辑像素）画布。

## 架构

| 层 | 技术 |
| --- | --- |
| 渲染底座 | D3D11 设备（硬件失败回退 WARP）+ D2D1 设备上下文（`ID2D1Factory1`）+ DirectWrite 文本 |
| 合成 | DirectComposition（`IDCompositionDesktopDevice`）；窗口 `WS_EX_NOREDIRECTIONBITMAP`，视觉树 `Present` → `Commit` 提交帧 |
| 窗口配方 | 无边框：`WM_NCCALCSIZE`(wParam=TRUE) 返回 0 自绘非客户区 + DWM 圆角（`DWMWA_WINDOW_CORNER_PREFERENCE`）+ 固定尺寸（`WM_GETMINMAXINFO` 钳制、无最大化） |
| 背景 | **Win11**：`DWMWA_SYSTEMBACKDROP_TYPE` Mica（OS build ≥ 22621；仅左栏/内容卡/底部条按 alpha 绘制，其余透明让 Mica 透出）。**Win10 降级**：不透明 Mica 风格渐变底 + 透明外扩边距内的 DComp 自绘阴影（不使用 `SetWindowRgn`）。 |
| 深浅色 | 跟随系统：读取 `AppsUseLightTheme` + `WM_SETTINGCHANGE`（ImmersiveColorSet）实时切换 |
| DPI | Per-Monitor-V2（`main.cpp` WinMain 最早期调用；动态 `GetProcAddress` 回退 `shcore` / `user32`）；绘制全程 DIP（96 基准），仅缓冲/窗口尺寸用物理像素 |
| 动画 | 自研 `spk::Animator`（缓动曲线 + 逐 tick 采样日志）；遵循 `SPI_GETCLIENTAREAANIMATION`（减少动画时禁用过渡） |
| 自包含 | 静态链接 libgcc/libstdc++（`-static-libgcc -static-libstdc++ -static`），仅附带 `libwinpthread-1.dll` |

## 页面模型（安装 5 页 + 维护/卸载页）

页面枚举唯一来源是 `src/render/app_state.h`，顺序冻结：`Welcome=0`、`License`、`Configure`、`Progress`、
`Finish`、`Maintenance=5`、`UninstallConfirm=6`、`Message=7`。维护/卸载页只允许追加到末尾，禁止重排 0..4。

### 安装流程（5 页）

1. **欢迎（0）** —— Logo、版本号（运行期取自 `SPKVERSION` 资源）、入场动画。
2. **许可协议（1）** —— `LICENSE` RCDATA 内嵌滚动框；未勾选同意时「下一步」禁用。
3. **配置（2）** —— 安装位置与安装选项合并在同一页：路径预填（NSIS 经 `/installdir "$INSTDIR"` 传入）、
   浏览（IFileOpenDialog，失败回退 `SHBrowseForFolderW`）、所需/可用空间与可写探测；
   桌面快捷方式=开、开始菜单=开、开机自启=关、安装完成后启动=开（默认值冻结）。
4. **安装进度（3）** —— 真实字节进度（permille `0..1000`，每文件完成回调并按 ~30fps 节流）；
   取消 = 安全停止 + 清理本次已写入文件。进入进度页时 NSIS 可能仍在把内嵌 payload
   解包到临时目录；此阶段按实际已解包字节推进 `0..500` permille，解包完成后由真实
   复制进度接管到 1000。解包长时间没有字节增长时会显示可见提示，`payload.error`
   出现时立即中止并展示可操作错误。
5. **完成（4）** —— 英雄页：成功图标 + 软件名称/版本 + 大按钮「立即启动」（去提权，见下文 UAC 章节）；
   页面内没有「打开安装目录」按钮。

> 配置页的「安装完成后启动」目前只写入配置状态，安装完成页不读取该选项；完成页始终显示
> 「立即启动」按钮，点击即启动。

### 维护 / 卸载流程（5..7）

- **维护页（5）** —— 显示检测到的安装目录、版本与状态；提供「修复」「卸载」「取消」。
  未检测到安装（`Sopeek.exe` 与 `_internal` 均不存在）时不进入维护页，改为显示可见错误页且不能修复。
- **卸载确认页（6）** —— 展示删除范围；「同时删除用户数据（设置、缓存、日志）」复选框默认关闭；
  提供「卸载」「取消」。`/uninstall` 模式的入口页就是本页。
- **通用消息页（7）** —— 关闭运行中的应用、修复失败/取消、卸载失败等可见错误与忙态；
  窗口保持打开，不会静默成功或自动关闭。

`tools/capture_installer.ps1` 的页面范围与上述一致：`install` 0..4、`maintenance` 5/6、`uninstall` 6。

## 生命周期与模式

| 模式 | 入口 | 交接过程 | 终态 |
| --- | --- | --- | --- |
| 全新安装 | 运行 setup，未检测到已安装 | setup 持 `SetupMutex` → 解包临时 GUI 并启动 → setup 立即解包 payload、写 `payload.ready` 后等待终端键 → GUI 交互收集选项、等哨兵后复制 payload → 写 `install-result.ini` → setup 走 `Section Install` 写卸载栈/快捷方式/注册表 | GUI 完成页；setup 退出 |
| 修复 | 已安装时再次运行 setup → 维护页「修复」 | GUI 预检 → 关闭运行中的应用 → 写 `maintenance-decision.ini`（`action=repair`）→ setup 回写 `ack=1`、释放 payload → GUI 覆盖式复制 → setup 走同一 `Section Install` 刷新元数据 | 成功 = 完成页（可选启动）；失败/取消 = 消息页 |
| 卸载（交互） | 应用和功能 → `UninstallHelper.exe /uninstall-launcher` | helper 启动 `SopeekUninstall.exe /uninstall` → UI 确认页写 `uninstall-request.ini` → helper 等待请求 → 分阶段删除 → 写 `uninstall-result.ini` → 等待 `ui_done`/UI 退出 → 删除 UI/DLL 后退出（helper 自身可能残留） | UI 完成页；helper 退出 |
| 卸载（静默） | `QuietUninstallString` → `UninstallHelper.exe /S`；或 launcher 找不到 UI 时自动降级 | 不启动 UI、不写 request；`delete_user_data` 强制为 0，直接分阶段删除并写 `uninstall-result.ini` | 无 UI；helper 退出 |
| 取消 | 维护页「取消」、卸载确认页「取消」、或关闭维护窗口 | 维护：写 `action=cancel` 后退出，setup 回 `ack=1` 并 `Abort`；维护模式的卸载确认页「取消」只返回维护页；`/uninstall` 模式的确认页「取消」写 `schema=1 cancelled=1` 后退出 | 不删除任何文件 |
| 第二实例 | 再次运行 setup / 第二个维护 UI | `SetupMutex` 或 `MaintenanceMutex` 已存在 → 激活已有窗口并退出，不重放 payload、不覆盖 decision/result、不写注册表 | 原实例继续 |

已安装判定只有两个信号：`$INSTDIR\Sopeek.exe` 或 `$INSTDIR\_internal`。结果 INI、快捷方式、
Add/Remove 条目都不能强制进入维护模式。

检测到安装后，setup 先调用 GUI 的 `/version-decision` 比较 `_internal\SPKVERSION` 与本安装包版本：
已安装版本更旧 → 按全新安装流程原地升级；相同或更新 → 进入维护页。版本判定失败（退出码非 `10`）
也回退到维护流程。

## 单实例互斥体（三个独立所有权）

常量唯一来源：`src/render/maintenance_protocol.h`；测试构建统一加 `.Test` 后缀。

| 互斥体 | 持有者 | 作用 |
| --- | --- | --- |
| `Local\SopeekSetupMutex` | NSIS setup（`.onInit` 到进程退出） | 防止两个 setup 同时解包/安装 |
| `Local\SopeekMaintenanceMutex` | C++ GUI（所有模式，到窗口销毁） | 防止第二个维护/卸载 UI |
| `Local\SopeekUninstallEngineMutex` | NSIS 卸载 helper（`un.onInit` 到退出） | 防止两个卸载引擎并行 |

三者禁止共用。setup 在启动 GUI 前会检查 setup、maintenance 与 uninstall-engine 互斥体；任一被占用即激活已有窗口后退出。

## 维护临时目录与退出码（M1 / H3）

- setup 在取得互斥体并通过单实例检查后，把 GUI + `libwinpthread-1.dll` 复制到
  `%TEMP%\SopeekMaintenance-<setup-pid>\`。setup 交接后可能先退出，因此该副本
  不依赖 `$PLUGINSDIR` 存活；GUI 仍加载 DLL 期间绝不删除 `$PLUGINSDIR`。
- 新 setup 在创建自己的副本之前，只扫描 `%TEMP%\SopeekMaintenance-*`：仅删除名称
  严格为「前缀 + 数字」、且目录 `LastWriteTime` 早于当前时间**精确 24 小时**（64 位 FILETIME
  比较，不是按日历日判断）的目录；非目录、reparse point、24 小时内的目录一律跳过；删除失败
  只忽略，不中止 setup。
- 维护/卸载 UI 正常退出时自清理自己的临时目录（异步，约 2 秒）；卸载 helper 在
  `unSecDeleteTerminal` 确认 UI 退出后，从 `$UnUiExe` 推导父目录，只有父目录严格等于
  `%TEMP%\SopeekMaintenance-<digits>` 时才递归删除（UI 已自清理时为空操作）。
  该清理永不删除 `$INSTDIR`、`$PLUGINSDIR` 或任意其他路径。
- H3：卸载 helper 启动 UI 失败时仍写 `stage=cancelled`、`done=1`、`warning=ui-launch-failed`，
  且不删除任何文件；内部卸载器进程退出码为 2。注意 NSIS 外层 stub 默认会把自身复制到
  `%TEMP%\~nsu*.tmp` 再运行并返回 0，因此 QA 使用 `_?=<installdir>` 直接运行安装目录中的卸载器，
  以观察真实退出码；产品契约仍以 `uninstall-result.ini` 的 `warning=ui-launch-failed` 为准。

## CLI 契约

GUI 解析入口：`src/main.cpp`。下表只列实际存在的参数。

| 参数 | 说明 |
| --- | --- |
| `/installdir <path>` | 安装目录；也用于维护/卸载定位协议 INI |
| `/payload <dir>` | payload 目录（默认 `.`） |
| `/payload-bytes <n>` | 构建期统计的 payload 精确字节数；`0` 或缺省时 GUI 回退为运行时扫描 |
| `/result <file>` | 安装结果 INI（默认 `payload\..\install-result.ini`） |
| `/version-decision` | 只比较已安装版本与本包版本后立即退出：`10` = 升级，`0` = 维护 |
| `/package-version <ver>` | `/version-decision` 使用的本安装包版本 |
| `/maintenance` | 进入维护模式（必须同时提供 `/decision`，否则显示可见错误页） |
| `/uninstall` | 进入卸载模式（入口为卸载确认页 6） |
| `/decision <file>` | 维护决策 INI 路径（`maintenance-decision.ini`） |
| `/setup-pid <pid>` | setup 进程 PID；用于监视 setup 提前退出 |
| `/payload-timeout <ms>` | 等待 `payload.ready` 的超时（`0` = 引擎默认） |
| `/helper <path>`、`/ui <path>` | NSIS helper → UI 的内部交接参数；UI 只解析，不消费 |
| `/helper-pid <pid>` | 启动 UI 的 helper PID；非 0 表示 helper 已启动 UI，协调器只附着而不重复启动 helper |
| `/elevated`、`/orig-sid <sid>`、`/orig-localappdata <path>` | 提权重启与交互用户一致性校验 |
| `/S`、`/uninstall-launcher`、`/uninstall-helper` | NSIS helper 内部标志；UI 只解析，不映射为 GUI 模式 |
| `/auto` | 开启无人值守（**仅 `SPK_TESTMODE` 构建生效**） |
| `/auto:opts=NNNN` | 四位 0/1：桌面 / 开始菜单 / 开机自启 / 完成后启动 |
| `/auto:page=N` | 到达第 N 页（0..7）后停住，仅用于截图/QA，不执行任何动作 |
| `/auto:mode=install\|maintenance\|uninstall` | 测试构建解析并写入诊断日志；实际 GUI 模式仍由 `/maintenance` / `/uninstall` 决定（未知值按 `install` 记录） |
| `/auto:action=repair\|uninstall\|cancel` | 维护/卸载页要执行的动作 |
| `/auto:delete-user-data=0\|1` | 卸载确认页的用户数据选择 |
| `/test-dump-maintenance=<file>` | 仅 `SPK_TESTMODE` 的诊断钩子：写维护检测结果后立即退出 |

**`/auto:*` 只存在于测试构建。** 生产构建会解析这些参数，但 `EnableAutoDrive` 是 no-op，生产构建
始终由 GUI 交互运行、不启用无人值守。`/auto:page=6` 只是停在卸载确认页，**不是**卸载动作；要执行卸载必须另给
`/auto:action=uninstall`，并通过 `/maintenance` 或 `/uninstall` 进入对应流程。

## 跨进程 INI 协议

维护/卸载协议 INI（`maintenance-decision.ini`、`uninstall-request.ini`、`uninstall-result.ini`）
位于安装目录，路径由双方按 `installDir` 推导；安装结果 INI 由 `/result` 指定（生产为
`$PLUGINSDIR\install-result.ini`）。节名/键名常量见 `src/render/maintenance_protocol.h`。
就绪判定只认终端键，绝不把「文件存在」当作完成。

### `maintenance-decision.ini`（GUI → setup）

```ini
[maintenance]
schema=1
pid=<GUI 进程 PID>
ack=0
action=repair   ; repair | uninstall | cancel（终端键，最后写）
```

- 写序：`schema` → `pid` → `ack=0` → `action`（终端键）。
- setup 轮询到非空 `action` 后写 `ack=1`；`repair` 才会释放 payload 并等待安装结果，
  `uninstall` / `cancel` 只回 ack 然后 `Abort`，绝不解包或执行 `Section Install`。
- 缺失、超时（默认 30 分钟）或 GUI 被看到后消失：setup 不动作并退出。

### `uninstall-request.ini`（UI → helper）

```ini
[uninstall]
schema=1
delete_user_data=0   ; 0 | 1
ui_pid=<UI 进程 PID>
ui_exe=<UI 可执行文件绝对路径>
```

- 写序：`schema` → `delete_user_data` → `ui_pid` → `ui_exe`（最后写，作为就绪信号）。
- 取消变体只写 `schema=1` 与 `cancelled=1`；helper 读到后不删除任何文件。
- UI 在卸载完成页关闭时向已有 request 追加 `ui_done=1`；helper 写完 `done=1` 后最多等待 60 秒。

### `uninstall-result.ini`（helper → UI）

```ini
[uninstall]
schema=1
stage=started        ; 见下方阶段
permille=0           ; 0..1000
error=               ; stage=failed 时的原因
warning=             ; 清理告警（不改变终态）
done=0               ; 0 | 1（终端键）
```

阶段与进度：`started`(0) → `removing_shortcuts`(100) → `removing_registry`(300) →
`removing_files`(500) → `removing_user_data`(800) → `done`(1000)；`failed` / `cancelled` 不是成功终态。
终端判定 = `done=1` 且 `stage` 为 `done` / `failed` / `cancelled`。`warning` 主要记录 `done=1` 之后的
清理告警，失败路径也可能附带；终态始终以 `stage` / `done` 为准。常见值：`install-dir-not-empty`、
`user-data-custom-overlap`、`ui-timeout`、`reboot_pending`、`ui-launch-failed`。

### `install-result.ini`（GUI → setup，冻结 schema）

- **路径**：NSIS 经 `/result "<绝对路径>"` 传入（生产为 `$PLUGINSDIR\install-result.ini`）；GUI 默认回退 `payload\..\install-result.ini`。
- **编码**：`WritePrivateProfileStringW`（UTF-16LE）。写入前**先以 UTF-16LE + BOM 预创建**文件；BOM 预创建只允许发生在结果写入例程内（安装/取消结束时），严禁在启动或开始安装时创建。
- **写入顺序**：先写 `[spk]` 占位节（`schema=1`，保证 `[install]` 永不为文件首节），随后写 `[install]`：
  - `dir`（安装目录，UTF-16）、`abort`（`0|1`，**恒写且最后写**）、`error`（成功为空串）、`desktop` / `startmenu` / `autostart`（`0|1`）。
  - **无 `launch` 键** —— 完成后启动由 GUI 独占实现，NSIS 不消费。
- **NSIS 就绪判定** = `[install] abort` 终端键非空（**不是**文件存在）：GUI 先创建文件、后填内容，仅凭存在性会误判；`dir` 写回严格发生在就绪之后。

## 修复语义

- **预检**：必须已检测到安装，且安装目录可写（写探针）；不满足时显示可见错误页，不写 `repair` 决策。
- **关闭应用**：修复前先关闭正在运行的 Sopeek；关闭失败可重试或取消，不会在应用占用文件时强行覆盖。
- **payload 修复**：用 payload 覆盖式复制，恢复缺失/损坏的程序文件；复制集合为 payload 全部文件，
  但跳过 `$INSTDIR\data` 与 `$INSTDIR\_internal\data`（用户数据）。覆盖成功后仅清理 `_internal` 中
  不在本次 payload 清单里的旧文件（尽力而为，被占用则保留，不影响成功判定）。
- **用户数据保留**：修复不删除配置、缓存、日志或任何用户数据；只恢复程序文件。
- **成功**：写 `action=repair` → setup ack 并释放 payload → GUI 写安装结果 → setup 走同一
  `Section Install` 刷新快捷方式、卸载信息与选项元数据 → 完成页（可选「立即启动 Sopeek」，默认不勾选）。
- **失败/取消**：**不回滚**，已覆盖的文件保持原样；错误统一带 `repair-` 前缀。窗口停留在维护模式的
  可见消息页并说明原因，绝不自动关闭或伪造成功；关闭窗口即退出（若尚未写过决策则补写 `cancel`）。
  不会出现部分删除类的破坏性动作。

## 卸载范围与用户数据

卸载按阶段执行，任一步失败写 `stage=failed` + `error=<具体路径/原因>`，不继续后续破坏性步骤：

- **快捷方式**：桌面与开始菜单（测试构建使用 `SopeekTest.lnk`）。
- **注册表**：卸载键（生产 `HKLM\...\Uninstall\Sopeek` 64 位视图，并清理遗留 32 位视图）
  与安装信息键（生产 `HKCU\Software\Sopeek`）。
- **程序文件**：`_internal`（保留 `_internal\data`）、`Sopeek.exe`、旧版 `Uninstall.exe`、
  临时/退休的 UI 与 DLL 文件。
- **用户数据（仅 `delete_user_data=1`）**：
  - 规范目录 `%LOCALAPPDATA%\Sopeek`（测试为 `%LOCALAPPDATA%\SopeekTestUserData`），
    其下 `data\` 是应用全部运行期数据的根（`config` / `assets` / `state` / `cache` /
    `logs` / `updates` / `diagnostics` / `temp`）；
  - `$INSTDIR\data`；
  - `$INSTDIR\_internal\data`。
- **`SPK_DATA_DIR` 自定义目录始终保留**：即使 `delete_user_data=1` 也不会删除它；若它与上述任一目标
  重叠，相关目标整体跳过并写 `warning=user-data-custom-overlap`。
- **helper 可能残留**：NSIS 自删除后原始 `UninstallHelper.exe` 可能仍在安装目录中，导致目录非空。
  这是预期结果：`stage=done`、`permille=1000`、`done=1`，并带 `warning=install-dir-not-empty`，
  **不是失败**。

失败/缺失路径：UI 缺失 → 静默卸载（`delete_user_data` 强制为 0）；helper 缺失 → 卸载入口不可用、
状态保持不变；用户在确认页取消 → `stage=cancelled`、`done=1`、不删除任何文件。

## 测试隔离

测试构建由 `-DSPK_TESTMODE=ON` 注入（`cmake/test_mode.cmake`），与生产完全隔离：

| 项目 | 测试值 |
| --- | --- |
| 安装目录 | `%LOCALAPPDATA%\SopeekTest` |
| 安装信息键 | `HKCU\Software\SopeekTest` |
| 卸载键 | `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest` |
| 规范用户数据 | `%LOCALAPPDATA%\SopeekTestUserData` |
| 自定义 `SPK_DATA_DIR` | `%LOCALAPPDATA%\SopeekTestSpkData` |
| 互斥体 | `Local\Sopeek*Mutex.Test` |
| 快捷方式 | `SopeekTest.lnk`（桌面/开始菜单） |

测试构建**不写生产注册表、不写生产 Run 键、不创建生产快捷方式、不触碰生产安装目录**；测试 setup 为
`RequestExecutionLevel user` 并完全跳过提权。生产构建的 GUI/Setup 分别为
`build/installer/SopeekInstaller.exe` 与 `build/Sopeek-<版本>-<平台>-<架构>.exe`
（例如 `build/Sopeek-2.0.0-windows-x64.exe`）；
测试产物在 `build/test-installer/`，QA 只运行测试 setup。

## QA

生命周期 QA（只跑 `SPK_TESTMODE` 测试 setup）：

```powershell
& .\packaging\installer\tools\qa_installer_lifecycle.ps1 -Mode all
```

- `-Mode`：`fresh`、`repair`、`cancel`、`second-instance`、`uninstall`、`failure`、
  `shortcut-isolation`、`uac-cancel`、`all`。
- 可选 `-Keep` 保留测试状态/证据现场，便于复现；不加时脚本会清理测试目录、进程、键与快捷方式。
- 证据目录默认 `.omo/evidence/sopeek-installer/t20/`（脚本内默认值，可用 `-EvidenceDir` 重定向）：
  `transcript.log`、`summary.json`、各场景 `.diag.log` 与截图。
- 在提权或环境受限的会话中，部分失败注入场景会标记为 SKIP（非失败）：`failure-kill-helper`
  （无法确定性杀 helper 窗口）、`failure-kill-setup-repair`（修复过快，无法确定性杀等待中的 setup）、
  `failure-readonly-nospace`（提权会话绕过 ACL，磁盘未接近满）、`uac-cancel`（提权会话，
  需标准用户或手工 UAC 取消）。

页面截图/回归：

```powershell
& .\packaging\installer\tools\capture_installer.ps1 -Mode maintenance -Page 5 `
    -Out .omo\evidence\installer\maintenance-page-5.png
```

页面范围：`install` 0..4、`maintenance` 5/6、`uninstall` 6；`maintenance -Page 6` 会自动追加
`/auto:action=uninstall`，仅用于导航到确认页。

## 构建与产物

在仓库根目录执行：

```powershell
& .\packaging\installer\build.ps1
```

构建要求：

- MSYS2 MinGW64 工具链（默认 `C:\msys64\mingw64\bin`）：`g++.exe`、`windres.exe`、
  `mingw32-make.exe`、`objdump.exe`
- `C:\Program Files\CMake\bin\cmake.exe`
- `C:\Program Files (x86)\NSIS\makensis.exe`

输出：

- `build/installer/SopeekInstaller.exe`：独立 GUI 安装器（同目录附 `libwinpthread-1.dll`）。
- `build/Sopeek-<版本>-<平台>-<架构>.exe`：最终安装包。名称由 `build.ps1` 依据
  `SPKVERSION` 生成，例如 `Sopeek-2.0.0-windows-x64.exe`、
  `Sopeek-2.0.0.nightly-20261114-windows-x64.exe`（nightly 版由 CI 改写 `SPKVERSION`）；
  平台/架构描述的是包所适配的系统（64 位 Windows），不是 NSIS 存根自身的位数。
  可用 `SPK_TARGET_PLATFORM` / `SPK_TARGET_ARCH` 覆盖。

**生产重建铁律**：修改本目录（`packaging/installer/**`）下任何代码/脚本/NSIS 后，必须在仓库根目录重新执行
`& .\packaging\installer\build.ps1` 并重新生成上述两个产物。**仅重建测试 GUI/测试安装包
（`tools\build_test_gui.ps1`、`tools\build_test_installer.ps1`，带 `SPK_TESTMODE`）不算完成**，
因为测试构建与出厂产品不一致。

重建后核对哈希与大小（不要在本文件硬编码某次构建的哈希；以本次实际构建结果为准）：

```powershell
Get-FileHash .\build\installer\SopeekInstaller.exe -Algorithm SHA256
Get-ChildItem .\build\Sopeek-*.exe | ForEach-Object { Get-FileHash $_.FullName -Algorithm SHA256 }
Get-Item .\build\installer\SopeekInstaller.exe, .\build\Sopeek-*.exe |
    Select-Object FullName, Length, LastWriteTime
```

## 部署结构

GUI 只把 `build/pyinstall/Sopeek` 的 payload 内容复制到用户选择的安装目录；卸载栈由 NSIS
`Section Install` 安装。最终安装目录结构：

```text
{app}\Sopeek.exe              # payload（GUI 复制）
{app}\_internal\...           # payload（GUI 复制）
{app}\SopeekUninstall.exe     # 卸载 UI（NSIS 安装）
{app}\UninstallHelper.exe     # 卸载 helper（NSIS 安装）
{app}\libwinpthread-1.dll     # MinGW runtime（NSIS 安装）
```

NSIS 不再显示默认安装页面，唯一可见的前端是 C++ GUI 窗口。NSIS 负责封装 payload、管理员权限、
卸载栈（UI + helper + MinGW runtime）、快捷方式、卸载信息和最终安装流程。

## 文件清单

- `src/main.cpp` —— WinMain、进程 DPI 感知、命令行解析、模式选择、提权重启、单实例接入。
- `src/installer_window.{h,cpp}` —— 无边框 DComp 窗口、Mica/降级路径、8 页状态机接线、模式分发、
  修复/卸载编排、输入分发、安装线程接线。
- `src/maintenance_detector.{h,cpp}` —— 只读检测安装目录/版本/选项。
- `src/single_instance.{h,cpp}` —— `MaintenanceMutex` 与既有窗口激活。
- `src/process_control.{h,cpp}` —— 精确关闭运行中的应用、提权检测。
- `src/uninstall_coordinator.{h,cpp}` / `src/uninstall_protocol.{h,cpp}` —— 卸载请求/结果/决策 INI 与 UI 侧编排。
- `src/render/` —— 渲染与 UI 模块：
  - `render_context.{h,cpp}`（D3D11 / D2D1 / DComp 底座）、`layout.{h,cpp}`（900×600 DIP shell 几何唯一来源）；
  - `theme.{h,cpp}`（token 表）、`text.{h,cpp}` / `glyphs.{h,cpp}` / `logo.{h,cpp}`、`animation.{h,cpp}`；
  - `controls_base.h` / `controls_basic.{h,cpp}`（Button / CheckBox / PathField）/ `controls_feedback.{h,cpp}`（ProgressBar / LicenseBox / StepItem）；
  - `pages_welcome.{h,cpp}` / `pages_setup.{h,cpp}` / `pages_progress.{h,cpp}` / `pages_maintenance.{h,cpp}`
    （安装 5 页 + 维护/卸载/消息页实现）、`app_state.h`（页面/选项/操作状态唯一来源）、
    `maintenance_protocol.h`（互斥体、注册表键、INI 名/键、阶段与超时唯一来源）、
    `messages.h`（冻结的 `WM_INSTALL_*`/permille 契约）；
  - `install_engine.{h,cpp}`（无窗口安装/修复引擎：payload 哨兵等待、字节进度、取消清理、修复跳过用户数据）、
    `launch_forward.{h,cpp}`（去提权启动转发）。
- `resources/app.rc` —— 应用图标、Logo RCDATA、`LICENSE` / `SPKVERSION` RCDATA、完整 VERSIONINFO。
- `resources/version.h.in` —— VERSIONINFO 模板，构建时由 CMake 写入 `version_gen.h`。
- `cmake/test_mode.cmake` —— `SPK_TESTMODE` 测试构建开关（默认 OFF）。
- `installer.nsi` —— NSIS 封装、单实例互斥体、同用户提权、payload 临时释放、`payload.ready` 哨兵、
  维护决策/安装结果等待、条件化快捷方式 / Run 键、安装卸载栈、分阶段卸载（双注册表视图、用户数据保留）。
- `tools/` —— `build_test_gui.ps1` / `build_test_installer.ps1`（测试构建）、`qa_installer_lifecycle.ps1`
  （生命周期 QA）、`capture_installer.ps1`（页面截图）、`make_stub_payload.ps1`（测试 payload）。
- `CMakeLists.txt` —— MinGW 构建；源文件经 `file(GLOB ...)` 自动收集（`src/*.cpp` + `src/render/*.cpp`，
  新增 `.cpp` 无需改本文件），`resources/app.rc` 显式列出。
- `build.ps1` —— MSYS2 MinGW64 + CMake + NSIS 一键构建入口。

## UAC 与提权限制

- NSIS 采用 `RequestExecutionLevel admin`，即**同用户提权**（不引入 UAC 插件），这是明确接受的已知限制：
  标准用户/多用户环境下仍需管理员凭据；提权进程写入的桌面/开始菜单快捷方式与 Run 键位于管理员别名 hive，
  标准用户账户不可见（需按用户迁移时另行处理）。
- GUI 本身是提权 NSIS `Exec` 的子进程（继承管理员令牌），因此**完成后启动必须去提权**：
  通过 `ShellExecuteW("open", "explorer.exe", "<INSTDIR>\Sopeek.exe")` 由 explorer 代为转发，
  使目标进程以**标准用户令牌**运行。安装完成页的「立即启动」按钮点击即执行该转发；
  目标 exe 缺失时窗口内提示且不崩溃。
