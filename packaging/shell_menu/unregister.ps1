<#
.SYNOPSIS
    注销 Sopeek 的稀疏包，并移除安装时导入的签名证书。

.DESCRIPTION
    卸载器以 admin 运行；这里先移除当前用户的包注册（新版右键菜单条目随之消失），
    再按安装期记录的指纹从 LocalMachine\TrustedPeople 精确删除证书，最后清掉记录文件。

    所有步骤都是尽力而为：包本来就不存在、证书已被移除都属于正常情况，
    不抛异常，避免卸载流程因为一个可选的菜单集成分支失败而整体失败。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir
)

$ErrorActionPreference = 'SilentlyContinue'

$install = $InstallDir
if (Test-Path -LiteralPath $install) {
    $install = (Resolve-Path -LiteralPath $install).ProviderPath
}

# 1) 移除包注册。包按用户注册，因此只影响当前用户；没有注册时静默跳过。
Get-AppxPackage -Name 'Sopeek.ShellMenu' | ForEach-Object {
    Remove-AppxPackage -Package $_.PackageFullName -ErrorAction SilentlyContinue
}

# 2) 移除安装期导入的证书（按记录的指纹，绝不动其它证书）。
$stateFile = Join-Path $install 'shell_menu_installed.txt'
if (Test-Path -LiteralPath $stateFile) {
    $thumbprint = (Get-Content -LiteralPath $stateFile -Raw).Trim()
    if ($thumbprint) {
        $certPath = "Cert:\LocalMachine\TrustedPeople\$thumbprint"
        if (Test-Path -LiteralPath $certPath) {
            Remove-Item -LiteralPath $certPath -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
}

exit 0
