<#
.SYNOPSIS
    Sopeek 一键发布构建：主程序打包 -> 安装器编译 -> NSIS 封装 -> 产物校验与哈希。

.DESCRIPTION
    按固定顺序串起发布链路，任一环节失败立即中止并返回非零退出码：

      1. 版本读取          读取仓库根目录 SPKVERSION
      2. 主程序打包        python Pyinstall_build.py  ->  build/pyinstall/Sopeek/
      3. 安装器构建        installer_duilib/build.ps1（CMake+MinGW 编译 GUI，再调用 makensis）
                           ->  build/installer/SopeekInstaller.exe
                           ->  build/Sopeek_NSIS_Setup.exe
      4. 产物校验与哈希    检查三个产物存在且非空，输出 SHA256 并写入清单

    脚本本身不执行任何 git 操作（不 add / commit / push）。

.PARAMETER SkipPyInstaller
    跳过第 2 步，复用已有的 build/pyinstall/Sopeek 产物（仅改动安装器时使用）。

.PARAMETER SkipInstaller
    跳过第 3 步，只做打包与校验（仅构建主程序时使用）。

.PARAMETER SkipBrandGate
    跳过旧品牌残留检查（scripts/verify_no_legacy_brand.ps1）。

.PARAMETER PyInstallerArgs
    透传给 Pyinstall_build.py 的额外参数，例如 -PyInstallerArgs '--no-clean'。

.PARAMETER ManifestPath
    发布清单输出路径，默认 build/release-manifest.json。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/build_release.ps1

.EXAMPLE
    # 只改了安装器 GUI，复用已有 payload
    powershell -ExecutionPolicy Bypass -File scripts/build_release.ps1 -SkipPyInstaller

.EXAMPLE
    # 只打主程序，跳过安装器
    powershell -ExecutionPolicy Bypass -File scripts/build_release.ps1 -SkipInstaller
#>
[CmdletBinding()]
param(
    [switch]$SkipPyInstaller,
    [switch]$SkipInstaller,
    [switch]$SkipBrandGate,
    [string[]]$PyInstallerArgs = @(),
    [string]$ManifestPath
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$VersionFile = Join-Path $RepoRoot 'SPKVERSION'
$PayloadRoot = Join-Path $RepoRoot 'build\pyinstall\Sopeek'
$InstallerExe = Join-Path $RepoRoot 'build\installer\SopeekInstaller.exe'
$InstallerDll = Join-Path $RepoRoot 'build\installer\libwinpthread-1.dll'

if (-not $ManifestPath) { $ManifestPath = Join-Path $RepoRoot 'build\release-manifest.json' }

$TotalWatch = [System.Diagnostics.Stopwatch]::StartNew()

function Write-Step {
    param([string]$Index, [string]$Text)
    Write-Host ''
    Write-Host ("=" * 68) -ForegroundColor DarkGray
    Write-Host ("[{0}] {1}" -f $Index, $Text) -ForegroundColor Cyan
    Write-Host ("=" * 68) -ForegroundColor DarkGray
}

function Write-Ok {
    param([string]$Text)
    Write-Host ("  OK  " + $Text) -ForegroundColor Green
}

function Write-Note {
    param([string]$Text)
    Write-Host ("      " + $Text) -ForegroundColor DarkGray
}

function Write-Warn {
    param([string]$Text)
    Write-Host ("  !!  " + $Text) -ForegroundColor Yellow
}

function Fail {
    param([string]$Text, [int]$Code = 1)
    Write-Host ''
    Write-Host ("BUILD FAILED: " + $Text) -ForegroundColor Red
    Write-Host ''
    exit $Code
}

# 优先使用仓库内 .venv，其次回退到 PATH 上的 python。
function Resolve-Python {
    $venv = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venv) { return $venv }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

# 安装包文件名形如 Sopeek-<版本>-<平台>-<架构>.exe（版本含 nightly 后缀时会更长），
# 因此按模式取「最新的一个」，而不是写死文件名。
function Resolve-SetupExe {
    param([string]$BuildDir)
    $candidates = @(Get-ChildItem -LiteralPath $BuildDir -Filter 'Sopeek-*.exe' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending)
    if ($candidates.Count -gt 0) { return $candidates[0].FullName }
    $legacy = Join-Path $BuildDir 'Sopeek_NSIS_Setup.exe'
    if (Test-Path -LiteralPath $legacy) { return $legacy }
    return $null
}

# ---------------------------------------------------------------------------
# 0. 预检
# ---------------------------------------------------------------------------
Write-Step '0/4' '环境预检'

if (-not (Test-Path -LiteralPath $VersionFile)) {
    Fail "缺少版本文件：$VersionFile" 2
}
$Version = (Get-Content -LiteralPath $VersionFile -TotalCount 1).Trim()
Write-Ok "版本号：$Version"

$Python = Resolve-Python
if (-not $Python) { Fail '未找到 Python 解释器（.venv 或 PATH）。' 2 }
Write-Ok "Python：$Python"
$PyVer = (& $Python --version 2>&1) -join ''
Write-Note $PyVer

if (-not $SkipPyInstaller) {
    & $Python -c "import PyInstaller" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail '当前 Python 环境缺少 PyInstaller，请先安装依赖（requirements.txt）。' 2
    }
    $piVer = (& $Python -c "import PyInstaller; print(PyInstaller.__version__)" 2>&1) -join ''
    Write-Ok "PyInstaller：$piVer"
}

if (-not $SkipInstaller) {
    # 与本机安装位置解耦：SPK_* 覆盖优先，其次本机默认路径，最后 PATH。
    # CI runner（GitHub Actions）的 CMake/NSIS/MSYS2 路径与本机不同。
    function Resolve-ToolPath {
        param([string]$Override, [string]$Preferred, [string]$CommandName, [string]$Label)
        if ($Override -and (Test-Path -LiteralPath $Override)) {
            return (Resolve-Path -LiteralPath $Override).ProviderPath
        }
        if ($Preferred -and (Test-Path -LiteralPath $Preferred)) { return $Preferred }
        $found = Get-Command $CommandName -ErrorAction SilentlyContinue
        if ($found) { return $found.Source }
        Fail ("缺少构建依赖：{0}（{1} 不存在，且 PATH 中没有 {2}）" -f $Label, $Preferred, $CommandName) 2
    }

    $cmakePath = Resolve-ToolPath -Override $env:SPK_CMAKE -Preferred 'C:\Program Files\CMake\bin\cmake.exe' -CommandName 'cmake' -Label 'CMake'
    Write-Ok "CMake：$cmakePath"

    $nsisPath = Resolve-ToolPath -Override $env:SPK_NSIS -Preferred 'C:\Program Files (x86)\NSIS\makensis.exe' -CommandName 'makensis' -Label 'NSIS (makensis)'
    Write-Ok "NSIS：$nsisPath"

    $mingwBin = $env:SPK_MINGW_BIN
    if (-not $mingwBin -or -not (Test-Path -LiteralPath (Join-Path $mingwBin 'g++.exe'))) {
        $mingwBin = 'C:\msys64\mingw64\bin'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $mingwBin 'g++.exe'))) {
        $gxx = Get-Command 'g++.exe' -ErrorAction SilentlyContinue
        if (-not $gxx) { Fail '缺少构建依赖：MinGW g++（SPK_MINGW_BIN、默认路径与 PATH 均未找到）' 2 }
        $mingwBin = Split-Path -Parent $gxx.Source
    }
    Write-Ok "MinGW：$mingwBin"

    $runtimeDll = Join-Path $mingwBin 'libwinpthread-1.dll'
    if (-not (Test-Path -LiteralPath $runtimeDll)) {
        Fail ("缺少构建依赖：MinGW 运行库（{0}）" -f $runtimeDll) 2
    }
    Write-Ok "libwinpthread：$runtimeDll"
}

# ---------------------------------------------------------------------------
# 1. 主程序打包（PyInstaller）
# ---------------------------------------------------------------------------
Write-Step '1/4' '主程序打包（PyInstaller）'

if ($SkipPyInstaller) {
    Write-Warn '已按 -SkipPyInstaller 跳过，复用现有 payload。'
} else {
    Push-Location $RepoRoot
    try {
        if ($PyInstallerArgs.Count -gt 0) {
            Write-Note ("参数：" + ($PyInstallerArgs -join ' '))
            & $Python 'Pyinstall_build.py' @PyInstallerArgs
        } else {
            & $Python 'Pyinstall_build.py'
        }
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($code -ne 0) { Fail "PyInstaller 打包失败（退出码 $code）。" 1 }
}

$payloadExe = Join-Path $PayloadRoot 'Sopeek.exe'
$payloadInternal = Join-Path $PayloadRoot '_internal'
if (-not (Test-Path -LiteralPath $payloadExe)) {
    Fail "payload 缺少主程序：$payloadExe（若已跳过打包，请先完整构建一次）" 1
}
if (-not (Test-Path -LiteralPath $payloadInternal)) {
    Fail "payload 缺少 _internal 目录：$payloadInternal" 1
}

$payloadBytes = (Get-ChildItem -LiteralPath $PayloadRoot -Recurse -File |
    Measure-Object -Property Length -Sum).Sum
Write-Ok ("payload：{0:N1} MB" -f ($payloadBytes / 1MB))

# ---------------------------------------------------------------------------
# 2. 安装器构建（C++ GUI + NSIS）
# ---------------------------------------------------------------------------
Write-Step '2/4' '安装器构建（C++ GUI + NSIS）'

if ($SkipInstaller) {
    Write-Warn '已按 -SkipInstaller 跳过。'
} else {
    $installerScript = Join-Path $RepoRoot 'installer_duilib\build.ps1'
    if (-not (Test-Path -LiteralPath $installerScript)) {
        Fail "缺少安装器构建脚本：$installerScript" 1
    }
    try {
        & $installerScript
    } catch {
        Fail ("安装器构建异常：" + $_.Exception.Message) 1
    }
    if ($LASTEXITCODE -ne 0) { Fail "安装器构建失败（退出码 $LASTEXITCODE）。" 1 }
}

# ---------------------------------------------------------------------------
# 3. 产物校验与哈希
# ---------------------------------------------------------------------------
Write-Step '3/4' '产物校验与哈希'

# 安装包名带版本/平台/架构，按模式解析（跳过安装器构建时可能为空）。
$SetupExe = Resolve-SetupExe -BuildDir (Join-Path $RepoRoot 'build')
if (-not $SkipInstaller -and -not $SetupExe) {
    Fail '未找到安装包产物（期望 build\Sopeek-<版本>-<平台>-<架构>.exe）。' 1
}

$artifacts = @(
    @{ Path = $InstallerExe; Name = 'SopeekInstaller.exe' },
    @{ Path = $InstallerDll; Name = 'libwinpthread-1.dll' }
)
if ($SetupExe) {
    $artifacts += @{ Path = $SetupExe; Name = (Split-Path -Leaf $SetupExe) }
}

$skipPaths = @()
if ($SkipInstaller) {
    # 跳过安装器构建时不因缺少安装器产物而失败，仅标注。
    $skipPaths = @($InstallerExe, $InstallerDll, $SetupExe)
}

$entries = New-Object System.Collections.Generic.List[object]
foreach ($a in $artifacts) {
    if ($SkipInstaller) {
        if (Test-Path -LiteralPath $a.Path) {
            $f = Get-Item -LiteralPath $a.Path
            $entries.Add([pscustomobject]@{
                name   = $a.Name
                path   = $a.Path.Substring($RepoRoot.Length + 1)
                bytes  = $f.Length
                sha256 = (Get-FileHash -LiteralPath $a.Path -Algorithm SHA256).Hash
                status = 'skipped-build'
            })
            Write-Warn ("{0}：已存在（本次未重建）" -f $a.Name)
        } else {
            Write-Warn ("{0}：不存在（本次未构建）" -f $a.Name)
        }
        continue
    }

    if (-not (Test-Path -LiteralPath $a.Path)) {
        Fail ("缺少产物：{0}" -f $a.Path) 1
    }
    $f = Get-Item -LiteralPath $a.Path
    if ($f.Length -le 0) { Fail ("产物为空文件：{0}" -f $a.Path) 1 }

    $hash = (Get-FileHash -LiteralPath $a.Path -Algorithm SHA256).Hash
    $entries.Add([pscustomobject]@{
        name   = $a.Name
        path   = $a.Path.Substring($RepoRoot.Length + 1)
        bytes  = $f.Length
        sha256 = $hash
        status = 'built'
    })
    Write-Ok ("{0}：{1:N2} MB" -f $a.Name, ($f.Length / 1MB))
    Write-Note ("SHA256 " + $hash)
}

# 版本一致性提醒（不阻断构建）：installer.nsi 里的版本串来自 SPKVERSION（由
# installer_duilib/build.ps1 计算后经 -D 传入）。字面量值若与 SPKVERSION 不一致就
# 提示；`${...}` 形式的宏引用属于正常情况，跳过。
$nsiPath = Join-Path $RepoRoot 'installer_duilib\installer.nsi'
if (Test-Path -LiteralPath $nsiPath) {
    $nsi = Get-Content -LiteralPath $nsiPath -Raw
    $expected = ($Version -replace '^[vV]', '')
    $found = [regex]::Matches($nsi, '"(?:ProductVersion|DisplayVersion)"\s+"([^"]+)"') |
        ForEach-Object { $_.Groups[1].Value } |
        Where-Object { $_ -notmatch '\$\{' } |
        Sort-Object -Unique
    foreach ($v in $found) {
        if ($v -ne $expected) {
            Write-Warn ("版本不一致：installer.nsi 为 {0}，SPKVERSION 为 {1}" -f $v, $expected)
        }
    }
}

# ---------------------------------------------------------------------------
# 4. 旧品牌残留检查（可选）+ 清单输出
# ---------------------------------------------------------------------------
Write-Step '4/4' '收尾检查与发布清单'

if ($SkipBrandGate) {
    Write-Warn '已按 -SkipBrandGate 跳过旧品牌检查。'
} else {
    $gate = Join-Path $RepoRoot 'scripts\verify_no_legacy_brand.ps1'
    if (Test-Path -LiteralPath $gate) {
        $gateJson = Join-Path $RepoRoot 'build\brand-gate.json'
        & powershell -NoProfile -ExecutionPolicy Bypass -File $gate -Root $RepoRoot -Json $gateJson | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok '旧品牌残留检查通过。'
        } else {
            # 不阻断构建：该检查反映的是仓库存量状态，失败只做提示。
            $hitCount = '?'
            $hitFiles = '?'
            if (Test-Path -LiteralPath $gateJson) {
                try {
                    $report = Get-Content -LiteralPath $gateJson -Raw | ConvertFrom-Json
                    $hitCount = $report.text_hits
                    $hitFiles = $report.text_hit_files
                } catch { }
            }
            Write-Warn ("旧品牌残留检查未通过：命中 {0} 处 / {1} 个文件（退出码 {2}）" -f $hitCount, $hitFiles, $LASTEXITCODE)
            Write-Note ("详情：" + $gateJson)
        }
    } else {
        Write-Warn '未找到旧品牌检查脚本，跳过。'
    }
}

$TotalWatch.Stop()
$modeParts = @()
if ($SkipPyInstaller) { $modeParts += 'skip-pyinstaller' }
if ($SkipInstaller)   { $modeParts += 'skip-installer' }
if ($SkipBrandGate)   { $modeParts += 'skip-brand-gate' }
$Mode = if ($modeParts.Count -eq 0) { 'full' } else { $modeParts -join '+' }

$manifest = [pscustomobject]@{
    product       = 'Sopeek'
    version       = $Version
    mode          = $Mode
    builtAt       = (Get-Date).ToString('o')
    durationSec   = [math]::Round($TotalWatch.Elapsed.TotalSeconds, 1)
    payloadBytes  = $payloadBytes
    artifacts     = $entries
}
$manifestDir = Split-Path -Parent $ManifestPath
if ($manifestDir -and -not (Test-Path -LiteralPath $manifestDir)) {
    New-Item -ItemType Directory -Force -Path $manifestDir | Out-Null
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ManifestPath -Encoding UTF8
Write-Ok ("发布清单：" + $ManifestPath)

Write-Host ''
Write-Host '==================== BUILD SUMMARY ====================' -ForegroundColor Cyan
Write-Host ("  版本        : {0}" -f $Version)
Write-Host ("  总耗时      : {0:N1} s" -f $TotalWatch.Elapsed.TotalSeconds)
foreach ($e in $entries) {
    Write-Host ("  {0,-24}: {1:N2} MB" -f $e.name, ($e.bytes / 1MB))
}
Write-Host ("  安装包      : {0}" -f $SetupExe)
Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ''

exit 0
