<#
.SYNOPSIS
    Sopeek 双击打包包装脚本：记录完整日志、调用发布构建、失败时保持窗口。

.DESCRIPTION
    build.cmd 通过本脚本完成一键打包。它负责：
      1. 把完整控制台输出（包括 Write-Host 与 CMake/MinGW/NSIS/PyInstaller 的原生输出）
         写入 build/logs/build-<时间戳>.log；
      2. 把参数以 hashtable splatting 传给 tools/build_release.ps1；
      3. 失败时打印日志最后 40 行和日志路径；
      4. 成功时列出最终安装包、大小与 SHA256。

    本脚本不负责中文路径切换，build_release.ps1 会在检测到非 ASCII 路径时自动
    切换到纯英文临时目录继续构建。

.PARAMETER NoPause
    build.cmd 已负责停窗时使用，避免按下两次回车。
#>
[CmdletBinding()]
param(
    [switch]$SkipPyInstaller,
    [switch]$SkipInstaller,
    [switch]$SkipBrandGate,
    [string[]]$PyInstallerArgs = @(),
    [string]$ManifestPath,
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'

# build.cmd 已执行 chcp 65001；这里同步 .NET 的输出编码，保证嵌套 PowerShell
# 子进程、CMake/MinGW/NSIS 的日志进入 Start-Transcript 时不会被按 GBK 误读。
try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = $utf8NoBom
    $OutputEncoding = $utf8NoBom
} catch { }

$repoRoot = Split-Path -Parent $PSScriptRoot
$buildRelease = Join-Path $PSScriptRoot 'build_release.ps1'
$logDir = Join-Path $repoRoot 'build\logs'
$logStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logPath = Join-Path $logDir ("build-{0}-{1}.log" -f $logStamp, $PID)

try { $Host.UI.RawUI.WindowTitle = 'Sopeek Release Build' } catch { }

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host '  Sopeek 一键打包' -ForegroundColor Cyan
Write-Host ('  仓库：' + $repoRoot)
Write-Host ('  时间：' + (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ''

$transcriptStarted = $false
try {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    Start-Transcript -Path $logPath -Force | Out-Null
    $transcriptStarted = $true
    Write-Host ('日志：' + $logPath) -ForegroundColor DarkGray
} catch {
    Write-Warning ('无法启动日志记录：' + $_.Exception.Message)
}

$exitCode = 1
try {
    if (-not (Test-Path -LiteralPath $buildRelease)) {
        throw "缺少发布构建脚本：$buildRelease"
    }

    $buildArgs = @{}
    if ($SkipPyInstaller) { $buildArgs['SkipPyInstaller'] = $true }
    if ($SkipInstaller) { $buildArgs['SkipInstaller'] = $true }
    if ($SkipBrandGate) { $buildArgs['SkipBrandGate'] = $true }
    if ($PyInstallerArgs.Count -gt 0) { $buildArgs['PyInstallerArgs'] = $PyInstallerArgs }
    if ($ManifestPath) {
        $buildArgs['ManifestPath'] = [System.IO.Path]::GetFullPath($ManifestPath)
    }

    $global:LASTEXITCODE = 0
    & $buildRelease @buildArgs
    if ($null -ne $LASTEXITCODE) {
        $exitCode = [int]$LASTEXITCODE
    } else {
        $exitCode = 0
    }
} catch {
    $exitCode = 1
    Write-Host ''
    Write-Host ('BUILD FAILED: ' + $_.Exception.Message) -ForegroundColor Red
    if ($_.ScriptStackTrace) {
        Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
    }
} finally {
    if ($transcriptStarted) {
        try { Stop-Transcript | Out-Null } catch { }
    }
}

if ($exitCode -ne 0) {
    Write-Host ''
    Write-Host '==================== 构建失败 ====================' -ForegroundColor Red
    if (Test-Path -LiteralPath $logPath) {
        Write-Host '日志最后 40 行：' -ForegroundColor Yellow
        try {
            Get-Content -LiteralPath $logPath -Tail 40 | ForEach-Object { Write-Host $_ }
        } catch { }
        Write-Host ('完整日志：' + $logPath) -ForegroundColor Yellow
    } else {
        Write-Host '未能写入日志文件。' -ForegroundColor Yellow
    }
} else {
    Write-Host ''
    Write-Host '==================== 构建完成 ====================' -ForegroundColor Green
    $buildDir = Join-Path $repoRoot 'build'
    $setup = @(Get-ChildItem -LiteralPath $buildDir -Filter 'Sopeek-*.exe' -File `
        -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if ($SkipInstaller) {
        Write-Host ('已跳过安装器，payload：' + (Join-Path $repoRoot 'build\pyinstall\Sopeek\Sopeek.exe'))
    } elseif ($setup.Count -gt 0) {
        $setupItem = $setup[0]
        $setupHash = (Get-FileHash -LiteralPath $setupItem.FullName -Algorithm SHA256).Hash
        Write-Host ('安装包：' + $setupItem.FullName)
        Write-Host ('大小  ：' + ('{0:N2} MB' -f ($setupItem.Length / 1MB)))
        Write-Host ('SHA256：' + $setupHash)
    } else {
        Write-Host '未找到最终安装包，请检查日志。' -ForegroundColor Yellow
    }
    if (Test-Path -LiteralPath $logPath) {
        Write-Host ('日志  ：' + $logPath) -ForegroundColor DarkGray
    }
}

$shouldPause = (-not $NoPause) -and ($env:SPK_BUILD_NO_PAUSE -ne '1')
if ($shouldPause) {
    Write-Host ''
    try { Read-Host '按 Enter 关闭窗口' | Out-Null } catch { }
}

exit $exitCode
