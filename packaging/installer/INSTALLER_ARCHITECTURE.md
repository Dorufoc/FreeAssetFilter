# Sopeek 安装器（D2D1 + DirectComposition / Install Design 复刻）

该目录是 Sopeek 安装器（C++ GUI + NSIS 封装）的工程目录。GUI 是一个自研 C++ Win32 程序：
无边框窗口 + DirectComposition 合成，固定 **640×540 DIP**（逻辑像素）画布。

配置页保留同意勾选。两份协议通过各自的链接进入独立阅读页（`License=1`），「返回」按钮与配置页主按钮位置一致。正文区域在 Mica 上使用单层半透明底色、等宽左右内边距和浮动滚动条。滚轮、高精度触控板滚动、Windows 触摸平移及键盘都可滚动正文。

### 安装流程（4 页）

1. **英雄页 / 欢迎（0）** —— 优先绘制 `install_design/bg.png`（`IDR_HERO_BG`=106），按设计稿词标区域等比定位；位图不可用时回退至矢量图形。
   页面保留「全能 · 高效 · 开源」（24 DIP）、「文件管理器」（32 DIP 粗体）和黑色「下一步」按钮。
2. **安装配置（2）** —— 设计稿 `安装配置.svg`：标题「安装配置」、路径框（564x36，右侧内嵌「浏览」，
   点击框内任意位置即打开 IFileOpenDialog，失败回退 `SHBrowseForFolderW`）、「可用空间 / 预计所需」、
   三个复选项（开机自启动=关、添加到右键菜单=开、在桌面创建快捷方式=开）、同意勾选（含两个协议链接）、
   黑色胶囊「下一步 >」+「返回」文字链。**未勾选同意、目标不可写或可用空间不足时「下一步」禁用**（40% 不透明度）。
3. **正在安装（3）** —— 窗口中部保留留白，底部显示 564×12 DIP 进度轨道、阶段文案与整数百分比，补充说明与阶段文案左对齐。
   **取消由标题栏 ✕ / ESC 触发**（走既有 `RaiseCancelIntent` → 引擎安全停止 + 清理本次写入）。
   真实字节进度（permille `0..1000`，每文件完成回调并按 ~30fps 节流）；进入进度页时 NSIS 可能仍在把
   内嵌 payload 解包到临时目录，此阶段按实际已解包字节推进至 80%，收到解包完成确认后，由文件复制及安装收尾接管 80%–100%。
   复制结束后进度停在 99.9%（界面按整数显示 99%）等待 NSIS 收尾，确认成功后显示 100% 并进入完成页。
   解包长时间没有字节增长时会显示可见提示，`payload.error` 出现时立即中止并展示可操作错误。
4. **安装完成（4）** —— 设计稿 `安装完成.svg`：同一组品牌图形 +「安装完成」(32px bold) +
   黑色胶囊「立即体验」（去提权启动，见下文 UAC 章节）+「退出」文字链。
   所有完成页共用 `bg.png`，卸载完成页主按钮为「再见」。

> 设计稿没有「开始菜单快捷方式」「安装完成后启动」勾选项：前者恒为创建（`startmenu=1` 写入结果 INI），
> 后者由完成页「立即体验」承担。

### 维护 / 卸载流程（5..7）

- **维护英雄页（5）** —— 根据版本提供「更新 / 修复」或「修复 / 卸载」。
- **卸载英雄页（6）与卸载选项（8）** —— 先显示 `bg.png` 英雄页，再进入安装配置样式的选项页，仅显示一个默认关闭的用户数据删除复选框。
- **通用消息页（7）** —— 关闭运行中的应用、修复失败/取消、卸载失败等可见错误与忙态；
  窗口保持打开，不会静默成功或自动关闭。

`tools/capture_installer.ps1` 支持 `install` 0–4、`maintenance` 5/6/8、`uninstall` 6/8。协议页为 1，测试环境变量 `SPK_TEST_OPEN_SHEET=eula` 可选择用户协议。

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

已检测到安装时直接进入维护英雄页，由 GUI 比较安装包与已装版本。新版提供「更新」「修复」，
同版提供「修复」「卸载」，旧版提供「卸载」。更新与修复先显示锁定的历史安装配置，
用户再次同意协议后才启动操作。新版安装包需要同版本安装包才能修复已装版本。

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
  - `dir`（安装目录，UTF-16）、`abort`（`0|1`，**恒写且最后写**）、`error`（成功为空串）、`desktop` / `startmenu` / `autostart` / `ctxmenu`（`0|1`）。
    `ctxmenu` 为「添加到右键菜单」，由 `Section Install` 落成（生产写 HKLM 64 位视图，测试写隔离的 HKCU）：
    - 两个 COM 类：`Software\Classes\CLSID\{...}\InprocServer32` → `"$INSTDIR\SopeekShellExt.dll"`，`ThreadingModel=Apartment`；
    - 文件动词 `Software\Classes\*\shell\SopeekOpenFile`（默认值「用Sopeek软件打开」，
      `%1`，`MultiSelectModel=Single`）；
    - 文件夹动词 `Software\Classes\Directory\shell\SopeekOpenFolder`（`%1`）与
      文件夹空白处动词 `Software\Classes\Directory\Background\shell\SopeekOpenFolder`（`%V`），
      默认值均为「使用Sopeek打开」。
    每个动词都写 `Icon` = `"$INSTDIR\Sopeek.exe",0`、`ExplorerCommandHandler` = 对应 CLSID（Windows 11
    经典菜单「显示更多选项」读取该值），以及 `command` 子键（`"$INSTDIR\Sopeek.exe" --open-path "%1|%V"`）
    供 Windows 10 与不支持 `IExplorerCommand` 的旧版本回退。值为 0 时删除上述动词与 CLSID 键（幂等清理），
    并把 `OptCtxMenu` 写入 `HKCU\Software\Sopeek`。注册/删除后调用
    `shell32::SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, 0, 0)` 让资源管理器立即重读菜单。
    - **Windows 11 顶层（现代）菜单另需稀疏包**：现代菜单只枚举具备包标识的应用通过清单声明的命令，
      纯注册表动词只能进「显示更多选项」。因此生产构建先写 CLSID、随后**在写动词之前**调用
      `RegisterShellMenuPackage`，执行 `shell_menu_register.ps1`：
      导入 `SopeekShellMenu.cer` 到 `LocalMachine\TrustedPeople` →
      `Add-AppxPackage -Path "$INSTDIR\SopeekShellMenu.msix" -ExternalLocation "$INSTDIR"`，
      结果写 `$INSTDIR\shell_menu_status.txt`（`status=ok|failed|missing`）；同版本重装若报
      `0x80073CFB`（同标识不同内容），脚本先 `Remove-AppxPackage` 再注册。
      包清单（`packaging/shell_menu/AppxManifest.xml`）必须**同时**声明两段扩展：
      `com:Extension Category="windows.comServer"`（两个 `com:Class`，`Path="SopeekShellExt.dll"`，
      `ThreadingModel="STA"`）与 `desktop4:Extension Category="windows.fileExplorerContextMenus"`
      （三条 `desktop5:ItemType`：`*` / `Directory` / `Directory\Background`，`Verb/@Clsid` 指向同两个
      CLSID）。**缺 comServer 段时现代菜单会静默跳过这些动词**（包状态仍为 Ok），这是本项目踩过的坑。
      注册表动词仍然照常写入，作为 Windows 10 与「显示更多选项」以及包注册失败时的回退。
      清单的 `uap:VisualElements` logo 由系统在 **ExternalLocation（安装目录）** 解析，不从 msix 读取，
      因此 payload 里额外带一份 `Assets\`（`build.ps1` 从 `packaging/shell_menu/Assets` 复制）：
      缺它不影响菜单与功能，但从现代菜单启动的应用在任务栏上会显示空白方块。卸载 Stage 3 一并
      `RMDir /r "$INSTDIR\Assets"`。
      注册成功后安装器会询问是否重启资源管理器（静默安装直接重启），DLL 与新包命令都要等它重载。
      失败只记日志、不阻断安装（禁用旁加载的机器仍可用经典菜单）。测试构建跳过该步，
      保持 HKCU 隔离与免提权。
      卸载在 Stage 3 删除文件前调用 `un.RemoveShellMenuPackage` 注销包并按记录的指纹删除证书。
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
  与安装信息键（生产 `HKCU\Software\Sopeek`）。另含资源管理器右键菜单：三处动词
  `Software\Classes\*\shell\SopeekOpenFile`、`Directory\shell\SopeekOpenFolder`、
  `Directory\Background\shell\SopeekOpenFolder`、两个 CLSID 键，以及旧版动词 `Sopeek`
  （父键递归删除 `command` 子键；删除前先 `ReadRegStr` 预检存在性——`DeleteRegKey` 对不存在的键
  会置错误标志，不预检会让从未勾选过右键菜单的正常卸载误报失败）。
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
| 右键菜单动词 | `HKCU\Software\Classes\*\shell\SopeekOpenFileTest` / `Directory\shell\SopeekOpenFolderTest` / `Directory\Background\shell\SopeekOpenFolderTest`（旧版 `SopeekTest` 一并清理） |
| 右键菜单 CLSID | `{ADD20484-57FF-4DEB-8561-AC7F04CAFDCB}`（文件）/ `{430F8D9E-4290-46F8-8E40-E38DAB04C5BD}`（文件夹） |
| 选项 DWORD | `HKCU\Software\SopeekTest` 的 `OptDesktop` / `OptStartmenu` / `OptAutostart` / `OptCtxMenu` |

测试构建**不写生产注册表、不写生产 Run 键、不创建生产快捷方式、不触碰生产安装目录**；测试 setup 为
`RequestExecutionLevel user` 并完全跳过提权。生产构建的 GUI/Setup 分别为
`build/installer/SopeekInstaller.exe` 与 `build/Sopeek-<版本>-<平台>-<架构>-<时间戳>.exe`
（例如 `build/Sopeek-2.0.0-windows-x64-261118153045.exe`）；
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

页面范围：`install` 0/2/3/4（页 1 = License 已废弃，`/auto:page=1` 会落到 2）、`maintenance` 5/6、
`uninstall` 6；`maintenance -Page 6` 会自动追加 `/auto:action=uninstall`，仅用于导航到确认页。

两个**仅测试构建**的 QA 环境变量（与 `/auto:*` 同性质，生产构建零残留）：

| 变量 | 作用 |
| --- | --- |
| `SPK_TEST_OPEN_SHEET=agpl\|eula` | 配合 `/auto:page=1` 选择独立协议阅读页的内容 |

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
- `build/Sopeek-<版本>-<平台>-<架构>-<时间戳>.exe`：最终安装包。名称由 `build.ps1` 依据
  `SPKVERSION` 与构建时间生成，例如 `Sopeek-2.0.0-windows-x64-261118153045.exe`、
  `Sopeek-2.0.0.nightly-20261114-windows-x64-261118153045.exe`（nightly 版由 CI 改写
  `SPKVERSION`）；时间戳为本地时间的 `yyMMddHHmmss`（年只取后两位），使每次构建产物唯一。
  平台/架构描述的是包所适配的系统（64 位 Windows），不是 NSIS 存根自身的位数。
  可用 `SPK_TARGET_PLATFORM` / `SPK_TARGET_ARCH` 覆盖。
  构建结束后 `build/` 下只保留最近 3 个时间戳安装包（`tools/build_release.ps1` 清理）。

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
- `src/installer_window.{h,cpp}` —— 无边框 DComp 窗口、窗口卡片/标题栏绘制、8 页状态机接线、模式分发、
  修复/卸载编排、输入分发、安装线程接线、协议弹窗宿主。
- `src/maintenance_detector.{h,cpp}` —— 只读检测安装目录/版本/选项。
- `src/single_instance.{h,cpp}` —— `MaintenanceMutex` 与既有窗口激活。
- `src/process_control.{h,cpp}` —— 精确关闭运行中的应用、提权检测。
- `src/uninstall_coordinator.{h,cpp}` / `src/uninstall_protocol.{h,cpp}` —— 卸载请求/结果/决策 INI 与 UI 侧编排。
- `src/render/` —— 渲染与 UI 模块：
  - `render_context.{h,cpp}`（D3D11 / D2D1 / DComp 底座）、`layout.{h,cpp}`（640×540 DIP shell 几何唯一来源 +
    `PageOffsetDip`）；
  - `theme.{h,cpp}`（唯一 token 表：设计稿浅色实测值 + 深色反推值）、`text.{h,cpp}` / `glyphs.{h,cpp}` /
    `logo.{h,cpp}`、`animation.{h,cpp}`；
  - `hero_art.{h,cpp}` + `hero_art_paths.inc` —— 设计稿品牌图形（四圆 + Sopeek 词标）的矢量重放：
    `.inc` 由 `tools/gen_hero_art.py` 从 `install_design/英雄页.svg` 的 `组_48` 生成（174 条命令，
    弧线已转三次贝塞尔，非零环绕），运行期只做 MoveTo/CubicTo/Close；
  - `controls_base.h` / `controls_basic.{h,cpp}`（Button：黑色胶囊 / 文字链；CheckBox：29x29 设计稿样式；
    PathField：浅灰输入框 + 内嵌「浏览」）/ `controls_feedback.{h,cpp}`（ProgressBar / LicenseBox / StepItem）；
  - `pages_welcome.{h,cpp}`（英雄页 + `design::` 几何常量 + `BaselineRect`/`CenteredBaselineRect`）/
    `pages_setup.{h,cpp}`（安装配置）/ `pages_progress.{h,cpp}`（正在安装 + 安装完成）/
    `pages_maintenance.{h,cpp}`（维护/卸载/消息页）、`license_sheet.{h,cpp}`（协议全文模态弹窗）、
    `app_state.h`（页面/选项/操作状态唯一来源）、
    `maintenance_protocol.h`（互斥体、注册表键、INI 名/键、阶段与超时唯一来源）、
    `messages.h`（冻结的 `WM_INSTALL_*`/permille 契约）；
  - `install_engine.{h,cpp}`（无窗口安装/修复引擎：payload 哨兵等待、字节进度、取消清理、修复跳过用户数据）、
    `launch_forward.{h,cpp}`（去提权启动转发）。
- `resources/app.rc` —— 应用图标、Logo RCDATA、`LICENSE` / `SPKVERSION` / `IDR_USERAGREEMENT`(104) /
  `IDR_HERO_BG`(106) RCDATA、完整 VERSIONINFO。
  `IDR_HERO_BG` 直接引用 `src/sopeek/resources/icons/install_design/bg.png`（设计稿背景图，单一数据源）。
- `resources/user-agreement.txt` —— 用户协议全文（UTF-8，内嵌为 `IDR_USERAGREEMENT`，可直接替换）。
- `resources/version.h.in` —— VERSIONINFO 模板，构建时由 CMake 写入 `version_gen.h`。
- `cmake/test_mode.cmake` —— `SPK_TESTMODE` 测试构建开关（默认 OFF）。
- `installer.nsi` —— NSIS 封装、单实例互斥体、同用户提权、payload 临时释放、`payload.ready` 哨兵、
  维护决策/安装结果等待、条件化快捷方式 / Run 键 / 右键菜单动词、安装卸载栈、分阶段卸载
  （双注册表视图、用户数据保留）。**该文件必须是带 BOM 的 UTF-8**（中文菜单文案 + makensis 的编码判定）。
- `tools/` —— `build_test_gui.ps1` / `build_test_installer.ps1`（测试构建）、`qa_installer_lifecycle.ps1`
  （生命周期 QA）、`capture_installer.ps1`（页面截图）、`make_stub_payload.ps1`（测试 payload）、
  `gen_hero_art.py`（从设计稿 SVG 重新生成词标路径数据）。
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
