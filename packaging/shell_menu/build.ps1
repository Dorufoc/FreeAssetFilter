# Sopeek 现代右键菜单稀疏包（MSIX）构建脚本。
#
# Windows 11 的新版右键菜单只显示带包标识的应用声明的命令；本脚本把
# AppxManifest.xml 渲染成真正的清单，生成只含清单与图标的稀疏包并签名。
# 安装（Add-AppxPackage -ExternalLocation）由安装器负责，见
# packaging\installer\installer.nsi。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File packaging\shell_menu\build.ps1 `
#       -OutputDirectory build\pyinstall\Sopeek
#
# 证书：默认复用 build\shell_menu\SopeekShellMenu.pfx；不存在时新建自签名
# 代码签名证书（Subject 必须与清单里的 Publisher 一致）。私钥只留在构建机，
# 安装器只携带导出的 .cer 供导入 TrustedPeople。

[CmdletBinding()]
param(
    [string]$OutputDirectory = '',
    [string]$Publisher = 'CN=Sopeek',
    [string]$Version = '',
    [string]$CMake = '',
    [string]$BuildDirectory = '',
    [string]$PfxPath = '',
    [string]$PfxPassword = 'SopeekShellMenuPfx!2026',
    [string]$MakeAppx = '',
    [string]$SignTool = '',
    [string]$MakePri = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step([string]$message) {
    Write-Host "[shell_menu] $message"
}

function Resolve-Tool([string]$explicit, [string[]]$candidates, [string]$name) {
    if ($explicit) {
        if (-not (Test-Path -LiteralPath $explicit)) {
            throw "Specified $name does not exist: $explicit"
        }
        return (Resolve-Path -LiteralPath $explicit).Path
    }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    throw "Required tool not found: $name"
}

$scriptDirectory = $PSScriptRoot
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDirectory '..\..')).Path

if ($repoRoot -match '[^\x00-\x7F]') {
    throw "Repository path contains non-ASCII characters, MSIX build requires an ASCII path: $repoRoot"
}

if (-not $BuildDirectory) {
    $BuildDirectory = Join-Path $repoRoot 'build\shell_menu'
}
$BuildDirectory = [System.IO.Path]::GetFullPath($BuildDirectory)

if (-not $OutputDirectory) {
    $OutputDirectory = $BuildDirectory
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)

# ---- 版本号 ---------------------------------------------------------------
if (-not $Version) {
    $versionFile = Join-Path $repoRoot 'SPKVERSION'
    if (-not (Test-Path -LiteralPath $versionFile)) {
        throw "SPKVERSION not found: $versionFile"
    }
    $rawVersion = (Get-Content -LiteralPath $versionFile -Encoding UTF8 | Select-Object -First 1).Trim()
    if ($rawVersion -match '^v?(\d+)\.(\d+)\.(\d+)') {
        $Version = '{0}.{1}.{2}.0' -f $Matches[1], $Matches[2], $Matches[3]
    } else {
        throw "Cannot derive a four-part MSIX version from SPKVERSION: $rawVersion"
    }
}
if ($Version -notmatch '^\d+\.\d+\.\d+\.\d+$') {
    throw "MSIX version must have four numeric parts: $Version"
}

if (-not $MakeAppx -or -not $SignTool -or -not $MakePri) {
    $kitsRoot = 'C:\Program Files (x86)\Windows Kits\10\bin'
    $makeAppxCandidates = @()
    $signToolCandidates = @()
    $makePriCandidates = @()
    if (Test-Path -LiteralPath $kitsRoot) {
        $sdkDirectories = Get-ChildItem -LiteralPath $kitsRoot -Directory |
            Where-Object { $_.Name -match '^10\.' } |
            Sort-Object { [version]($_.Name) } -Descending
        foreach ($sdk in $sdkDirectories) {
            $makeAppxCandidates += (Join-Path $sdk.FullName 'x64\makeappx.exe')
            $signToolCandidates += (Join-Path $sdk.FullName 'x64\signtool.exe')
            $makePriCandidates += (Join-Path $sdk.FullName 'x64\makepri.exe')
        }
    }
    if (-not $MakeAppx) {
        $MakeAppx = Resolve-Tool '' $makeAppxCandidates 'makeappx.exe'
    }
    if (-not $SignTool) {
        $SignTool = Resolve-Tool '' $signToolCandidates 'signtool.exe'
    }
    if (-not $MakePri) {
        $MakePri = Resolve-Tool '' $makePriCandidates 'makepri.exe'
    }
}

# ---- 清单布局 -------------------------------------------------------------
$layoutDirectory = Join-Path $BuildDirectory 'layout'
if (Test-Path -LiteralPath $layoutDirectory) {
    Remove-Item -LiteralPath $layoutDirectory -Recurse -Force
}
New-Item -ItemType Directory -Path $layoutDirectory -Force | Out-Null

$assetsSource = Join-Path $scriptDirectory 'Assets'
if (-not (Test-Path -LiteralPath $assetsSource)) {
    throw "MSIX assets missing: $assetsSource (run packaging\shell_menu\make_assets.py)"
}
$assetsTarget = Join-Path $layoutDirectory 'Assets'
New-Item -ItemType Directory -Path $assetsTarget -Force | Out-Null
Copy-Item -Path (Join-Path $assetsSource '*') -Destination $assetsTarget -Force

$manifestTemplate = Get-Content -LiteralPath (Join-Path $scriptDirectory 'AppxManifest.xml') -Raw -Encoding UTF8
$manifest = $manifestTemplate.Replace('{{PUBLISHER}}', $Publisher).Replace('{{VERSION}}', $Version)
$manifestPath = Join-Path $layoutDirectory 'AppxManifest.xml'
[System.IO.File]::WriteAllText($manifestPath, $manifest, [System.Text.UTF8Encoding]::new($false))

$packagePath = Join-Path $BuildDirectory 'SopeekShellMenu.msix'
if (Test-Path -LiteralPath $packagePath) {
    Remove-Item -LiteralPath $packagePath -Force
}

# ---- 资源索引（resources.pri）---------------------------------------------
# 任务栏图标要「不镀底板」，必须让系统按 targetsize / altform-unplated 限定符
# 解析 VisualElements 里的 logo；限定符解析依赖包内的 resources.pri。没有它，
# Windows 只认基名资源、并给图标垫一层 BackgroundColor（transparent 时会退化
# 成系统强调色，实测出现红底/藏青底方块）。
$priConfig = Join-Path $BuildDirectory 'priconfig.xml'
if (Test-Path -LiteralPath $priConfig) {
    Remove-Item -LiteralPath $priConfig -Force
}
Write-Step 'Creating resource index config'
& $MakePri createconfig /cf $priConfig /dq 'en-US' /o | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "makepri createconfig failed with exit code $LASTEXITCODE"
}
$priOutput = Join-Path $layoutDirectory 'resources.pri'
if (Test-Path -LiteralPath $priOutput) {
    Remove-Item -LiteralPath $priOutput -Force
}
Write-Step 'Indexing assets into resources.pri'
& $MakePri new /pr $layoutDirectory /cf $priConfig /of $priOutput /in 'Sopeek.ShellMenu' /o | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "makepri new failed with exit code $LASTEXITCODE"
}

Write-Step "Packing sparse package ($Version, $Publisher)"
# /nv：稀疏包的程序文件位于安装目录（Add-AppxPackage -ExternalLocation），不在包内，
# 因此跳过「清单声明的 exe 必须存在于包内」这类语义校验（schema 校验仍由 /nv 前的
# 解析阶段保证，任何清单结构错误依旧会失败）。
& $MakeAppx pack /d $layoutDirectory /p $packagePath /o /nv
if ($LASTEXITCODE -ne 0) {
    throw "makeappx failed with exit code $LASTEXITCODE"
}

# ---- 签名证书 -------------------------------------------------------------
if (-not $PfxPath) {
    $PfxPath = Join-Path $BuildDirectory 'SopeekShellMenu.pfx'
}
$PfxPath = [System.IO.Path]::GetFullPath($PfxPath)
$certificatePath = [System.IO.Path]::ChangeExtension($PfxPath, '.cer')

if (-not (Test-Path -LiteralPath $PfxPath)) {
    Write-Step "Creating self-signed code signing certificate for $Publisher"
    $certificate = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $Publisher `
        -FriendlyName 'Sopeek Shell Menu' `
        -KeyUsage DigitalSignature `
        -KeyExportPolicy Exportable `
        -KeyLength 2048 `
        -HashAlgorithm 'SHA256' `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -NotAfter (Get-Date).AddYears(10)
    $securePassword = ConvertTo-SecureString -String $PfxPassword -Force -AsPlainText
    Export-PfxCertificate -Cert $certificate -FilePath $PfxPath -Password $securePassword | Out-Null
    Export-Certificate -Cert $certificate -FilePath $certificatePath -Type CERT | Out-Null
} elseif (-not (Test-Path -LiteralPath $certificatePath)) {
    $securePassword = ConvertTo-SecureString -String $PfxPassword -Force -AsPlainText
    $imported = Import-PfxCertificate -FilePath $PfxPath -Password $securePassword -CertStoreLocation 'Cert:\CurrentUser\My'
    Export-Certificate -Cert $imported -FilePath $certificatePath -Type CERT | Out-Null
}

Write-Step 'Signing package'
& $SignTool sign /fd SHA256 /f $PfxPath /p $PfxPassword /a $packagePath
if ($LASTEXITCODE -ne 0) {
    throw "signtool failed with exit code $LASTEXITCODE"
}

# ---- 产物 -----------------------------------------------------------------
if (-not (Test-Path -LiteralPath $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}
$targetPackage = Join-Path $OutputDirectory 'SopeekShellMenu.msix'
$targetCertificate = Join-Path $OutputDirectory 'SopeekShellMenu.cer'
Copy-Item -LiteralPath $packagePath -Destination $targetPackage -Force
Copy-Item -LiteralPath $certificatePath -Destination $targetCertificate -Force

# 资源索引必须同时落到「外部位置（安装目录）」：稀疏包在运行期从
# -ExternalLocation 解析 VisualElements 的 logo，按 targetsize / altform-unplated
# 限定符选区，而限定符解析读的正是外部位置根目录下的 resources.pri。只把 pri
# 打进 msix（WindowsApps 里）不会生效——实测任务栏仍是「强调色底板 + logo」。
Copy-Item -LiteralPath $priOutput -Destination (Join-Path $OutputDirectory 'resources.pri') -Force

# 注册/卸载脚本随包一起放进安装目录：安装器与卸载器都以 admin 调用它们，
# 由脚本负责信任证书、Add-AppxPackage -ExternalLocation、以及卸载时的精确清理。
$targetRegister = Join-Path $OutputDirectory 'shell_menu_register.ps1'
$targetUnregister = Join-Path $OutputDirectory 'shell_menu_unregister.ps1'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'register.ps1') -Destination $targetRegister -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'unregister.ps1') -Destination $targetUnregister -Force

Write-Step "Package : $targetPackage"
Write-Step "Certificate: $targetCertificate"
Write-Step 'Done'
