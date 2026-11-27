# Sopeek 稀疏包（Windows 11 新版右键菜单）

Windows 11 顶层（现代）右键菜单**只列出具备包标识的应用**通过应用清单声明的命令。
安装器写得再完整的 `Software\Classes\...\shell\<verb>` 注册表项，也只会出现在
“显示更多选项”（经典菜单）里。要让“使用Sopeek打开 / 用Sopeek软件打开”直接出现在
新版菜单，需要给已安装的传统 Win32 目录额外注册一个**稀疏包**。

本目录负责生成那个包，并随安装包一起发布：

```text
SopeekShellMenu.msix          稀疏包：只有清单 + 图标，没有任何可执行文件
SopeekShellMenu.cer           包的签名证书（CN=Sopeek，自签名，10 年）
shell_menu_register.ps1       安装时：信任证书 + Add-AppxPackage -ExternalLocation
shell_menu_unregister.ps1     卸载时：Remove-AppxPackage + 按指纹删除证书
```

它们与 `SopeekShellExt.dll`、`Sopeek.exe` 一样被安装到 `$INSTDIR`，包通过
`-ExternalLocation "$INSTDIR"` 关联到这些真实文件——所以升级应用时**不需要重新打包**
MSIX，只要版本号不变。

## 清单要点

**只声明 `windows.fileExplorerContextMenus` 是不够的**：微软
[Integrate a packaged desktop app with File Explorer](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/integrate-packaged-app-with-file-explorer)
要求同一份清单里再用 `windows.comServer` 把列出的 CLSID 注册成**包内 COM 服务器**，
否则新版菜单会静默跳过这些动词（表现就是“完全看不到条目”，而注册表与包状态都正常）。
CLSID 必须同时出现在 `com:Class/@Id`、`com:Class/@Path` 所指 DLL 与本机注册表
`InprocServer32` 里，三处一致。

```xml
<Identity Name="Sopeek.ShellMenu" Publisher="CN=Sopeek" Version="2.0.0.0" ProcessorArchitecture="x64" />
<Properties>
  <uap10:AllowExternalContent>true</uap10:AllowExternalContent>   <!-- 必须在 Properties 内 -->
</Properties>
<Application Id="Sopeek" Executable="Sopeek.exe"
             uap10:TrustLevel="mediumIL" uap10:RuntimeBehavior="win32App">
  <uap:VisualElements DisplayName="Sopeek" AppListEntry="none" ... />   <!-- 见「开始菜单」小节 -->
  <Extensions>
    <!-- ① 包内 COM 服务器：缺了这段，新版菜单不会加载我们的动词 -->
    <com:Extension Category="windows.comServer">
      <com:ComServer>
        <com:SurrogateServer DisplayName="Sopeek context menu">
          <com:Class Id="02F1BD14-..." Path="SopeekShellExt.dll" ThreadingModel="STA" />
          <com:Class Id="39F01A4C-..." Path="SopeekShellExt.dll" ThreadingModel="STA" />
    <!-- ② 菜单动词 -->
    <desktop4:Extension Category="windows.fileExplorerContextMenus">
      <desktop4:FileExplorerContextMenus>
        <desktop5:ItemType Type="*">                    <desktop5:Verb Id="SopeekOpenFile"   Clsid="02F1BD14-..."/>
        <desktop5:ItemType Type="Directory">            <desktop5:Verb Id="SopeekOpenFolder" Clsid="39F01A4C-..."/>
        <desktop5:ItemType Type="Directory\Background"> <desktop5:Verb Id="SopeekOpenBackground" Clsid="39F01A4C-..."/>
```

`Path` 是相对于 `-ExternalLocation`（安装目录）的路径，所以 `SopeekShellExt.dll` 必须
留在 `$INSTDIR` 里——这也让扩展自己的 `ModuleDirectory()` 能找到同目录的 `Sopeek.exe`。

### 任务栏图标：logo 也走 ExternalLocation

清单里 `uap:VisualElements` 的 `Square44x44Logo` / `Square150x150Logo` **不是**从 msix 里读的，
系统按 **外部位置**（`-ExternalLocation`，即安装目录）解析——微软 sparse packaging 指南原文：
“the manifest's logos are resolved from the external location at runtime, not from the
identity-only .msix … copy them next to your exe”。

因此 `Assets\` 必须随 payload 落到安装目录（`packaging/installer/build.ps1` 会把
`packaging/shell_menu/Assets` 复制成 `build/pyinstall/Sopeek/Assets`）。缺了它不会影响右键
菜单与功能，但从「现代菜单」启动的应用在任务栏上会显示**空白灰色方块**（实测：把 msix 内的
logo 涂成纯红重装无效，把 `Assets\` 放到安装目录后立刻变成红色 → 证明系统读的是外部位置）。

### 任务栏图标的底板颜色：`BackgroundColor` + `resources.pri` 一起决定

`uap:VisualElements@BackgroundColor` 决定任务栏给这个包画什么颜色的圆角底板（图标是透明 PNG，
底板会从四周露出来）。写成 `transparent` 时系统**不会**真的透明，而是退化成 **系统的强调色**——
本机强调色是红色（`HKCU\Software\Microsoft\Windows\DWM` 的 `ColorizationColor=0xC4E74856`），
于是任务栏按钮变成「红底 + Sopeek logo」（2026-11-27 实测）。

想要**完全不要底板**（只显示带透明通道的原始图标），必须让系统按限定符挑选「无底板」资源：
`Assets\Square44x44Logo.targetsize-<n>_altform-unplated.png`，而限定符解析依赖 **资源索引
`resources.pri`**，并且这个 pri 必须和 `Assets\` 一样落在 **外部位置（安装目录）**——稀疏包运行期
就是从外部位置解析 logo 的。实测对比：

| 安装目录内容 | 任务栏表现 |
|---|---|
| 有 `Assets\`、无 `resources.pri` | 强调色（红）底板 + logo |
| 有 `Assets\` + `resources.pri`（本方案） | 无底板，显示原始透明图标 |

`resources.pri` 由 `build.ps1` 用 `makepri createconfig` + `makepri new` 生成，随 msix 一起
打包，同时复制到 payload（安装目录根）；安装器 `register.ps1` 缺它时给 warning，卸载时删除。

### 开始菜单：有且只有一个入口

这个包的唯一职责是给安装目录申请包标识，它**不是**一个独立应用。清单里必须给
`uap:VisualElements` 写 `AppListEntry="none"`：

- 不写时，开始菜单会同时出现「安装器创建的经典快捷方式」和「包应用」两个一模一样的
  Sopeek 图标（2026-11-27 实测）。
- 写了之后，包入口从开始菜单/应用列表隐藏，开始菜单只剩快捷方式那一个；任务栏图标与
  `shell:AppsFolder\<PFN>!Sopeek` 启动都不受影响（任务栏仍按 AUMID 归组，功能不变）。

配套的系统门禁（在 `installer.nsi::RegisterShellMenuPackage` 里）：Windows 10（build < 22000）
**完全不注册**这个包——Win10 没有新版右键菜单，注册只会平白多出一个开始菜单入口；此时
`shell_menu_status.txt` 写 `status=skipped-os`，右键功能由注册表动词在经典菜单里提供。若
Win10 机器上残留了旧版本注册过的同名包，跳过分支会顺手执行 `shell_menu_unregister.ps1`
把它撤掉，保证升级后不再重名。

几条容易踩的 schema 规则（都已按 Windows SDK 10.0.26100 的 xsd 核对）：

| 要求 | 错误写法会得到 |
|---|---|
| `uap10:AllowExternalContent` 放在 `<Properties>` 内 | `error C00CE014`（Package 下不允许该元素） |
| 扩展元素用 `desktop4:Extension` + `desktop4:FileExplorerContextMenus` | “Extensions 中的 desktop5:Extension 无效” |
| 条目用 `desktop5:ItemType` | `desktop4:ItemType` 的 Type 不接受 `Directory` / `Directory\Background` |
| `Verb/@Clsid` 不带花括号 | `error C00CE169`（不符合 GUID pattern） |
| 打包时加 `/nv` | `Sopeek.exe doesn't exist in the package`（稀疏包本来就不含 exe） |

## 构建

正常路径无需手工执行：`packaging/installer/build.ps1` 会在统计 payload 体积前调用本目录的
`build.ps1`，把 `.msix` / `.cer` / 两个 `.ps1` 直接放进 `build/pyinstall/Sopeek/`。

单独构建（调试用）：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\shell_menu\build.ps1 `
    -OutputDirectory build\shell_menu_out
```

- 依赖 Windows SDK 的 `makeappx.exe` 与 `signtool.exe`（脚本自动在
  `C:\Program Files (x86)\Windows Kits\10\bin\10.*\x64\` 下找最新版本）。
- 图标由 `make_assets.py` 从 `assets\Sopeek.png` 生成到 `build\shell_menu\Assets`；
  缺图标时构建会直接失败并提示先运行 `python packaging\shell_menu\make_assets.py`。
- 证书缓存在 `build\shell_menu\SopeekShellMenu.pfx`（口令默认
  `SopeekShellMenuPfx!2026`，可用 `-PfxPath` / `-PfxPassword` 覆盖）。**证书一旦更换，
  已安装的旧包必须卸载重装**：清单 Publisher 必须与签名证书主题一致。

## 安装 / 卸载语义

- 安装（生产构建）：`Section Install` 先写两个 CLSID，然后**在写动词之前**调用
  `RegisterShellMenuPackage`（执行 `shell_menu_register.ps1`），接着照常写三项注册表动词：
  - 注册表动词是 Windows 10 与「显示更多选项」的可靠回退，也是包注册被机器策略拦下时
    唯一还能用的入口，所以**始终写入**。
  - 代价：Windows 11 若同时枚举包命令与注册表动词，经典菜单可能出现两条相同条目；
    以实测结果为准再收敛（宁可重复，不可缺失）。
  - 脚本把证书导入 `LocalMachine\TrustedPeople`（安装器以 admin 运行，这是 `Add-AppxPackage`
    接受自签名包的前提），记录指纹到 `$INSTDIR\shell_menu_installed.txt`，结果写入
    `$INSTDIR\shell_menu_status.txt`（`status=ok|failed|missing|skipped-os`），便于静默安装后排查。
  - Windows 10（build < 22000）走 `status=skipped-os`：不注册包、并撤掉可能残留的旧包，
    开始菜单因此始终只有一个入口。
- 同版本重装：`-ForceUpdateFromAnyVersion` 只覆盖“版本号更低”的场景；同一个版本号但
  清单/签名变过会报 `0x80073CFB`，此时 `register.ps1` 会先 `Remove-AppxPackage` 再注册。
- 失败不阻断安装：机器策略禁用旁加载时，经典菜单仍然可用，安装照常完成。
- 测试构建（`SPK_TESTMODE`）**不注册包**：测试安装器不提权、只用 HKCU 隔离，注册机器级
  证书会让测试污染真实环境。
- 卸载：卸载器在删除文件前执行 `shell_menu_unregister.ps1`（移除当前用户的包注册 + 按记录
  的指纹删除证书），随后删除 msix/cer/脚本与状态文件；残留文件按 `reboot_pending` 处理。
- 包按用户注册：同一台机器的其他用户登录后需要各自执行一次维护安装（或由安装器在
  该用户下运行）才会看到新版菜单条目。
- 包注册成功后安装器会询问是否重启资源管理器（静默安装直接重启）：DLL 与新包命令都要等
  Explorer 重新加载才会生效。

## 排查

菜单没出现时按顺序检查：

1. `$INSTDIR\shell_menu_status.txt` —— 注册是否成功、失败时的退出码与 PowerShell 错误。
2. `Get-AppxPackage -Name Sopeek.ShellMenu` —— 包是否在**当前用户**注册。
3. `Get-ChildItem Cert:\LocalMachine\TrustedPeople | Where Subject -eq 'CN=Sopeek'`
   —— 证书是否被信任（清空后用安装器修复安装可重建）。
4. `%LOCALAPPDATA%\Sopeek\data\logs\shell-ext.log` —— 点击后是否真的进到 `Invoke`，
   以及解析到的目标目录和 `hr=`。
5. 重新登录或重启 Explorer：新注册的包命令有时要等下一次菜单枚举才出现。
