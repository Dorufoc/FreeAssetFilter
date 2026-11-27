<#
.SYNOPSIS
    注册 Sopeek 的稀疏包（sparse package），让 Windows 11 新版右键菜单出现
    「用Sopeek软件打开」与「使用Sopeek打开」。

.DESCRIPTION
    Windows 11 的现代（顶层）右键菜单只会枚举**具备包标识**的应用通过清单声明的
    命令；纯注册表 ExplorerCommandHandler 只能进入「显示更多选项」的经典菜单。
    因此安装器在写完注册表 CLSID 之后，还需要把随安装包发布的稀疏包注册到当前用户。

    稀疏包本身不含程序文件：清单里声明的 Sopeek.exe 与 SopeekShellExt.dll 都在
    -InstallDir 指向的安装目录里，由 Add-AppxPackage -ExternalLocation 关联。

    本脚本要求管理员权限（安装器本身以 admin 运行）：给 LocalMachine\TrustedPeople
    导入随包的签名证书，否则 Add-AppxPackage 会以 0x800B0109（根证书不受信任）失败。

.PARAMETER InstallDir
    Sopeek 安装目录，内部应存在 SopeekShellMenu.msix / SopeekShellMenu.cer。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir
)

$ErrorActionPreference = 'Stop'

$install = (Resolve-Path -LiteralPath $InstallDir).ProviderPath
$msix = Join-Path $install 'SopeekShellMenu.msix'
$cer = Join-Path $install 'SopeekShellMenu.cer'
$stateFile = Join-Path $install 'shell_menu_installed.txt'

if (-not (Test-Path -LiteralPath $msix)) {
    throw "缺少稀疏包: $msix"
}
if (-not (Test-Path -LiteralPath $cer)) {
    throw "缺少签名证书: $cer"
}
# 稀疏包的清单 logo 由系统在**外部位置**（安装目录）里解析，而不是从 msix 读取；
# 缺少 Assets 时应用能启动，但任务栏按钮会显示空白占位方块。这里只做提示，
# 不阻断注册（右键菜单本身不受影响）。
$assets = Join-Path $install 'Assets'
if (-not (Test-Path -LiteralPath $assets)) {
    Write-Warning "缺少稀疏包图标目录（任务栏图标会显示空白）: $assets"
}
# 资源索引（resources.pri）必须和 Assets 一样落在外部位置：系统靠它按
# targetsize / altform-unplated 限定符挑选「无底板」图标。缺了它任务栏会退回
# 「强调色方块 + logo」。同样只提示，不阻断注册。
$pri = Join-Path $install 'resources.pri'
if (-not (Test-Path -LiteralPath $pri)) {
    Write-Warning "缺少资源索引（任务栏图标会带一层底板）: $pri"
}

# 1) 信任签名证书。安装器已提权，因此写的是机器的 TrustedPeople 存储；
#    已经存在时跳过，避免每次维护安装都重复导入。
$cert = Get-PfxCertificate -FilePath $cer
$thumbprint = $cert.Thumbprint
$trusted = Get-ChildItem -Path Cert:\LocalMachine\TrustedPeople |
    Where-Object { $_.Thumbprint -eq $thumbprint }
if (-not $trusted) {
    Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\TrustedPeople | Out-Null
}

# 2) 注册稀疏包。维修/升级安装时同名同发布者的包已存在，先用
#    -ForceUpdateFromAnyVersion 覆盖注册；该开关只覆盖「版本号更低」的场景，
#    同样版本号但清单/资源变过（重新打包过签名内容）仍会报 0x80073CFB
#    「提供的程序包已安装，且禁止重新安装」，此时必须先卸载再注册。
try {
    Add-AppxPackage -Path $msix -ExternalLocation $install -ForceUpdateFromAnyVersion -ErrorAction Stop
} catch {
    $existing = Get-AppxPackage -Name 'Sopeek.ShellMenu'
    if (-not $existing) {
        throw
    }
    Write-Output "shell-menu: existing package needs replace, removing $($existing.PackageFullName)"
    Remove-AppxPackage -Package $existing.PackageFullName -ErrorAction Stop
    Add-AppxPackage -Path $msix -ExternalLocation $install -ErrorAction Stop
}

$package = Get-AppxPackage -Name 'Sopeek.ShellMenu'
if (-not $package) {
    throw '稀疏包注册后仍查询不到 Sopeek.ShellMenu'
}

# 3) 记录证书指纹，供卸载时精确移除信任，不影响其它证书。
Set-Content -LiteralPath $stateFile -Value $thumbprint -Encoding ascii

Write-Output "shell-menu: $($package.PackageFullName) cert=$thumbprint"
