# Sopeek 资源管理器右键菜单扩展

`SopeekShellExt.dll` 是一个进程内 COM 服务器（`IExplorerCommand`），为资源管理器提供
两项独立的右键菜单：

| 菜单项 | 作用位置 | 动词键 |
|---|---|---|
| 用Sopeek软件打开 | 任意文件 | `Software\Classes\*\shell\SopeekOpenFile` |
| 使用Sopeek打开 | 文件夹图标 | `Software\Classes\Directory\shell\SopeekOpenFolder` |
| 使用Sopeek打开 | 文件夹内空白处 | `Software\Classes\Directory\Background\shell\SopeekOpenFolder` |

不写入任何文件后缀关联：三项都是独立的菜单项，点击后统一执行
`Sopeek.exe --open-path "<路径>"`，由应用自身完成“进入目录 / 定位并选中文件”。

## 为什么需要 COM 扩展

Windows 11 的新版（现代）右键菜单不再读取旧式 `command` 子键，只接受
`ExplorerCommandHandler` 指向的 `IExplorerCommand` 实现。注册表动词键上写
`ExplorerCommandHandler` = CLSID、并在
`HKLM\Software\Classes\CLSID\{...}\InprocServer32` 指向本 DLL，就能被经典菜单
（Win10、Win11 的“显示更多选项”）加载，点击时由 Explorer 直接调用本 DLL 的 `Invoke`。

**但只有注册表还不够**：Win11 顶层的新版菜单只枚举“具备包标识（package identity）”
的应用通过应用清单声明的命令。因此现代菜单条目由同目录的稀疏包
（`packaging/shell_menu/`，`SopeekShellMenu.msix`）声明：清单里三条
`desktop5:ItemType` 分别对应 `*` / `Directory` / `Directory\Background`，`Clsid`
指向下面这两个（生产）CLSID。包只提供标识与清单，真正的代码仍由本 DLL + `Sopeek.exe`
在安装目录里执行（`Add-AppxPackage -ExternalLocation`）。

保留 `command` 子键作为第二个回退：经典菜单在未加载 COM 的机器上仍可用。

## 路径解析

- 文件、文件夹图标：菜单目标由 `IShellItemArray` 首项给出（`SIGDN_FILESYSPATH`）。
- 文件夹空白处：`IShellItemArray` 为空，先由 `IObjectWithSite` 收到的 Explorer site
  依次尝试 `IShellBrowser::QueryActiveShellView` → `IFolderView::GetFolder`
  → `IPersistFolder2::GetCurFolder`；站点缺失时再枚举 `CLSID_ShellWindows`，
  用前台窗口句柄匹配对应的资源管理器窗口后再取 `QueryActiveShellView`。
- 两者都失败时仍然启动 `Sopeek.exe`（不带 `--open-path`），保证“点了至少有反应”，
  并把 `hr=` / `source=` / `target=` 追加到
  `%LOCALAPPDATA%\Sopeek\data\logs\shell-ext.log` 便于排查。

## 注册（由安装器完成）

`packaging/installer/installer.nsi` 在 `Section Install` 内按“添加到右键菜单”勾选写：

```text
HKLM\Software\Classes\CLSID\{02F1BD14-A1B5-4B9E-9E10-C756D537FDA0}
        (default)            = Sopeek file context menu
        \InprocServer32      = "<INSTDIR>\SopeekShellExt.dll"
        \InprocServer32\ThreadingModel = Apartment
HKLM\Software\Classes\CLSID\{39F01A4C-DD1D-48D2-8FB3-0E0C76B336BC}
        ... 同上（文件夹/空白处）
```

测试构建（`SPK_TESTMODE`）改用 HKCU 与另一对 CLSID
（`{ADD20484-57FF-4DEB-8561-AC7F04CAFDCB}` / `{430F8D9E-4290-46F8-8E40-E38DAB04C5BD}`），
动词名加 `Test` 后缀，保证不会覆盖真实安装的菜单项。

卸载时删除上述动词、CLSID 与本 DLL（被占用则改名为 `.old` 后 `Delete /REBOOTOK`）。

## 构建

```powershell
powershell -ExecutionPolicy Bypass -File packaging\shell_ext\build.ps1 `
    -Destination build\shell_ext_out
```

正常路径不需要手动执行：`packaging/installer/build.ps1` 会先构建本 DLL 并复制到
PyInstaller payload（`build/pyinstall/Sopeek/`），随后由安装器随应用一起安装到
`$INSTDIR`。

依赖：MinGW-w64 g++（静态链接 libgcc/libstdc++）、CMake、`objdump`。构建脚本会断言产物
不依赖 `libgcc_s_seh-1.dll` / `libstdc++-6.dll` / `libwinpthread-1.dll`，导出表只有
`DllCanUnloadNow` 与 `DllGetClassObject`。

## 注意

- 源码为 UTF-8（含中文菜单字面量），CMake 已加 `-finput-charset=UTF-8`。
- 引用计数从 1 起算：`CreateInstance` 内部会先 `QueryInterface` 再 `Release` 掉本地引用，
  构造函数若只 `InterlockedIncrement(&g_object_count)` 而不同步 `g_lock_count`，
  会导致返回给 Explorer 的指针被提前 `delete`。
- 修改本目录后需要重新执行安装器生产重建（`packaging/installer/build.ps1`），
  否则安装包内仍是旧的 DLL。
