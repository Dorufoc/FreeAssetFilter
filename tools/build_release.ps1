<#
.SYNOPSIS
    Sopeek 一键发布构建：主程序打包 -> 安装器编译 -> NSIS 封装 -> 产物校验与哈希。

.DESCRIPTION
    按固定顺序串起发布链路，任一环节失败立即中止并返回非零退出码：

      1. 版本读取          读取仓库根目录 SPKVERSION
      2. 主程序打包        python packaging/build.py  ->  build/pyinstall/Sopeek/
      3. 安装器构建        packaging/installer/build.ps1（CMake+MinGW 编译 GUI，再调用 makensis）
                           ->  build/installer/SopeekInstaller.exe
                           ->  build/Sopeek-<版本>-<平台>-<架构>.exe
      4. 产物校验与哈希    检查三个产物存在且非空，输出 SHA256 并写入清单

    脚本本身不执行任何 git 操作（不 add / commit / push）。

    如果仓库路径包含非 ASCII 字符（如中文），CMake + MinGW 无法可靠构建。脚本会
    明确提示该路径不受支持，但不会中止，而是把工作区镜像到纯英文临时目录继续：
    优先 C 盘根目录，C 盘可用空间不足 5 GB 时依次尝试 D、E……；成功后把产物复制
    回原仓库 build\ 并清理临时目录，失败时保留临时目录便于排查。

.PARAMETER SkipPyInstaller
    跳过第 2 步，复用已有的 build/pyinstall/Sopeek 产物（仅改动安装器时使用）。

.PARAMETER SkipInstaller
    跳过第 3 步，只做打包与校验（仅构建主程序时使用）。

.PARAMETER SkipBrandGate
    跳过旧品牌残留检查（tools/verify_no_legacy_brand.ps1）。

.PARAMETER PyInstallerArgs
    透传给 packaging/build.py 的额外参数，例如 -PyInstallerArgs '--no-clean'。

.PARAMETER ManifestPath
    发布清单输出路径，默认 build/release-manifest.json。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools/build_release.ps1

.EXAMPLE
    # 只改了安装器 GUI，复用已有 payload
    powershell -ExecutionPolicy Bypass -File tools/build_release.ps1 -SkipPyInstaller

.EXAMPLE
    # 只打主程序，跳过安装器
    powershell -ExecutionPolicy Bypass -File tools/build_release.ps1 -SkipInstaller
#>
[CmdletBinding()]
param(
    [switch]$SkipPyInstaller,
    [switch]$SkipInstaller,
    [switch]$SkipBrandGate,
    [string[]]$PyInstallerArgs = @(),
    [string]$ManifestPath,
    # 内部参数：中文路径重定向到英文临时目录时，通过 JSON 文件传递原始参数，
    # 避免把含空格/以 - 开头的 PyInstaller 参数重新拼成命令行。
    [string]$BuildSettingsPath,
    [switch]$FromAsciiWorkspace
)

$ErrorActionPreference = 'Stop'

# 与 build.cmd 的 chcp 65001 保持一致，避免中文日志和子进程输出按 GBK 误读。
try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = $utf8NoBom
    $OutputEncoding = $utf8NoBom
} catch { }

# 读取内部参数文件。仅用于父进程把本次构建参数原样交给临时目录中的子构建。
if ($BuildSettingsPath) {
    if (-not (Test-Path -LiteralPath $BuildSettingsPath)) {
        throw "找不到构建参数文件：$BuildSettingsPath"
    }
    $buildSettings = Get-Content -LiteralPath $BuildSettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($null -ne $buildSettings.skipPyInstaller) { $SkipPyInstaller = [bool]$buildSettings.skipPyInstaller }
    if ($null -ne $buildSettings.skipInstaller)   { $SkipInstaller   = [bool]$buildSettings.skipInstaller }
    if ($null -ne $buildSettings.skipBrandGate)   { $SkipBrandGate   = [bool]$buildSettings.skipBrandGate }
    if ($null -ne $buildSettings.pyInstallerArgs) {
        $PyInstallerArgs = @($buildSettings.pyInstallerArgs |
            Where-Object { $null -ne $_ } |
            ForEach-Object { [string]$_ })
    }
    if ($null -ne $buildSettings.manifestPath -and
        -not [string]::IsNullOrWhiteSpace([string]$buildSettings.manifestPath)) {
        $ManifestPath = [string]$buildSettings.manifestPath
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$VersionFile = Join-Path $RepoRoot 'SPKVERSION'
$PayloadRoot = Join-Path $RepoRoot 'build\pyinstall\Sopeek'
$InstallerExe = Join-Path $RepoRoot 'build\installer\SopeekInstaller.exe'
$InstallerDll = Join-Path $RepoRoot 'build\installer\libwinpthread-1.dll'

if (-not $ManifestPath) { $ManifestPath = Join-Path $RepoRoot 'build\release-manifest.json' }

# 中文路径重定向时，临时目录不会复制 .venv；通过环境变量让子构建继续使用
# 原仓库里的虚拟环境解释器，避免把 1 GB 左右的 .venv 复制到临时目录。
if (-not $env:SPK_PYTHON) {
    $repoVenvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $repoVenvPython) {
        $env:SPK_PYTHON = $repoVenvPython
    }
}

$TotalWatch = [System.Diagnostics.Stopwatch]::StartNew()
$BuildStartUtc = [DateTime]::UtcNow

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

# 优先使用 SPK_PYTHON / 仓库内 .venv，其次回退到 PATH 上的 python。
function Resolve-Python {
    if ($env:SPK_PYTHON -and (Test-Path -LiteralPath $env:SPK_PYTHON)) {
        return $env:SPK_PYTHON
    }
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
# 中文路径处理：CMake/MinGW 不能可靠处理非 ASCII 源码路径。这里不中止，
# 而是把工作区镜像到纯英文临时目录继续打包，成功后把产物复制回原仓库。
# ---------------------------------------------------------------------------
function Test-NonAsciiPath {
    param([string]$Path)
    return ($Path -match '[^\x00-\x7F]')
}

function Get-AsciiWorkspaceDrive {
    $minFreeBytes = [int64]5GB
    $drives = @([System.IO.DriveInfo]::GetDrives() |
        Where-Object {
            $_.DriveType -eq [System.IO.DriveType]::Fixed -and $_.IsReady
        })
    # C 盘优先，其余按盘符顺序（D、E……）。
    $drives = @($drives | Sort-Object `
        @{ Expression = { if ($_.Name -ieq 'C:\') { 0 } else { 1 } } }, `
        @{ Expression = { $_.Name } })

    if ($drives.Count -eq 0) {
        throw '没有找到可用的本地固定磁盘，无法创建纯英文临时构建目录。'
    }

    $reports = New-Object System.Collections.Generic.List[string]
    foreach ($drive in $drives) {
        $free = [int64]$drive.AvailableFreeSpace
        $freeGb = [math]::Round($free / 1GB, 2)
        if ($free -lt $minFreeBytes) {
            Write-Warn ("{0} 可用 {1} GB，小于 5 GB，跳过。" -f $drive.Name, $freeGb)
            $reports.Add(("{0} 可用 {1} GB（不足 5 GB）" -f $drive.Name, $freeGb))
            continue
        }

        $probe = Join-Path $drive.RootDirectory.FullName `
            ('SopeekBuildProbe_' + [guid]::NewGuid().ToString('N'))
        try {
            New-Item -ItemType Directory -Path $probe -ErrorAction Stop | Out-Null
            Remove-Item -LiteralPath $probe -Recurse -Force -ErrorAction Stop
            Write-Ok ("临时构建盘：{0}（可用 {1} GB）" -f $drive.Name, $freeGb)
            return $drive.RootDirectory.FullName
        } catch {
            Write-Warn ("{0} 不可写，跳过：{1}" -f $drive.Name, $_.Exception.Message)
            $reports.Add(("{0} 不可写：{1}" -f $drive.Name, $_.Exception.Message))
            if (Test-Path -LiteralPath $probe) {
                try { Remove-Item -LiteralPath $probe -Recurse -Force -ErrorAction Stop } catch { }
            }
        }
    }

    throw ("没有本地磁盘满足临时构建目录要求（至少 5 GB 可用空间且可写）。`n" +
        "已检查：`n  " + ($reports -join "`n  "))
}

function Copy-DirectoryTree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [switch]$Mirror
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "源目录不存在：$Source"
    }
    $destParent = Split-Path -Parent $Destination
    if ($destParent -and -not (Test-Path -LiteralPath $destParent)) {
        New-Item -ItemType Directory -Force -Path $destParent | Out-Null
    }

    $rcArgs = @($Source, $Destination)
    if ($Mirror) { $rcArgs += '/MIR' } else { $rcArgs += '/E' }
    $rcArgs += @('/COPY:DAT', '/DCOPY:T', '/R:2', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    if (-not $Mirror) {
        $rcArgs += @('/XD', '.git', '.venv', 'build', 'dist', 'target', 'node_modules',
            '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
            '/XF', '*.pyc', '*.pyo')
    }

    $output = @(& robocopy @rcArgs 2>&1)
    $code = $LASTEXITCODE
    if ($code -ge 8) {
        $tail = ($output | Select-Object -Last 15) -join "`n"
        throw ("目录复制失败（robocopy 退出码 {0}）：`n{1}" -f $code, $tail)
    }
}

function Write-BuildSettingsFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    # manifestPath 留空：子构建写临时目录内的清单，父进程复制回原仓库指定的位置。
    [pscustomobject]@{
        skipPyInstaller = [bool]$SkipPyInstaller
        skipInstaller   = [bool]$SkipInstaller
        skipBrandGate   = [bool]$SkipBrandGate
        pyInstallerArgs = @([string[]]$PyInstallerArgs)
        manifestPath    = $null
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Invoke-AsciiWorkspaceBuild {
    $workspace = $null
    $workspaceRepo = $null

    try {
        Write-Host ''
        Write-Host ("=" * 68) -ForegroundColor DarkGray
        Write-Host '[路径] 切换到纯英文临时构建目录' -ForegroundColor Cyan
        Write-Host ("=" * 68) -ForegroundColor DarkGray
        Write-Warn "仓库路径包含非 ASCII 字符（如中文），CMake + MinGW 不支持在该路径下构建。"
        Write-Note ("原仓库：$RepoRoot")

        $driveRoot = Get-AsciiWorkspaceDrive
        $workspaceName = 'SopeekBuild_{0}_{1}' -f `
            (Get-Date -Format 'yyyyMMdd_HHmmss'), `
            ([guid]::NewGuid().ToString('N').Substring(0, 6))
        $workspace = Join-Path $driveRoot $workspaceName
        New-Item -ItemType Directory -Path $workspace -ErrorAction Stop | Out-Null
        Write-Note ("临时目录：$workspace")

        [pscustomobject]@{
            sourceRepo = $RepoRoot
            createdAt  = (Get-Date).ToString('o')
            processId  = $PID
        } | ConvertTo-Json -Depth 3 |
            Set-Content -LiteralPath (Join-Path $workspace 'workspace.json') -Encoding UTF8

        $workspaceRepo = Join-Path $workspace 'repo'
        Copy-DirectoryTree -Source $RepoRoot -Destination $workspaceRepo
        Write-Ok '源码已镜像到英文临时目录（排除 .git / .venv / build / 缓存）。'

        if ($SkipPyInstaller) {
            $sourcePayload = Join-Path $PayloadRoot 'Sopeek.exe'
            if (-not (Test-Path -LiteralPath $sourcePayload)) {
                throw "已指定 -SkipPyInstaller，但现有 payload 缺少主程序：$sourcePayload"
            }
            if (-not (Test-Path -LiteralPath (Join-Path $PayloadRoot '_internal'))) {
                throw "已指定 -SkipPyInstaller，但现有 payload 缺少 _internal 目录：$PayloadRoot"
            }
            Copy-DirectoryTree -Source $PayloadRoot `
                -Destination (Join-Path $workspaceRepo 'build\pyinstall\Sopeek') -Mirror
            Write-Ok '已有 payload 已复制到临时目录。'
        }

        $settingsPath = Join-Path $workspace 'build-settings.json'
        Write-BuildSettingsFile -Path $settingsPath

        $childScript = Join-Path $workspaceRepo 'tools\build_release.ps1'
        if (-not (Test-Path -LiteralPath $childScript)) {
            throw "临时目录缺少构建脚本：$childScript"
        }

        $powerShellExe = (Get-Process -Id $PID).Path
        if (-not $powerShellExe -or -not (Test-Path -LiteralPath $powerShellExe)) {
            throw '无法定位当前 PowerShell 解释器，不能启动临时目录中的子构建。'
        }

        Write-Host ''
        Write-Host ("在临时目录继续构建：{0}" -f $workspaceRepo) -ForegroundColor Cyan
        Push-Location $workspaceRepo
        try {
            # 通过管道把子进程输出重新写入当前 PowerShell 主机，这样双击包装脚本的
            # Start-Transcript 才能记录 CMake / MinGW / NSIS / PyInstaller 的完整输出。
            & $powerShellExe -NoProfile -ExecutionPolicy Bypass `
                -File $childScript -BuildSettingsPath $settingsPath -FromAsciiWorkspace `
                2>&1 | ForEach-Object { Write-Host $_ }
            $childCode = $LASTEXITCODE
        } finally {
            Pop-Location
        }

        if ($null -eq $childCode) { $childCode = 1 }
        $childCode = [int]$childCode
        if ($childCode -ne 0) {
            Write-Host ''
            Write-Host ("子构建失败（退出码 {0}）。" -f $childCode) -ForegroundColor Red
            Write-Host ("临时工作目录已保留：$workspace") -ForegroundColor Yellow
            Write-Host ("排查完成后可删除：Remove-Item -LiteralPath '$workspace' -Recurse -Force") `
                -ForegroundColor DarkGray
            return $childCode
        }

        Write-Host ''
        Write-Host ("=" * 68) -ForegroundColor DarkGray
        Write-Host '[复制] 把临时目录产物复制回原仓库' -ForegroundColor Cyan
        Write-Host ("=" * 68) -ForegroundColor DarkGray

        if (-not $SkipPyInstaller) {
            $tempPayload = Join-Path $workspaceRepo 'build\pyinstall\Sopeek'
            if (-not (Test-Path -LiteralPath (Join-Path $tempPayload 'Sopeek.exe'))) {
                throw "临时构建没有生成 payload：$tempPayload"
            }
            Copy-DirectoryTree -Source $tempPayload `
                -Destination (Join-Path $RepoRoot 'build\pyinstall\Sopeek') -Mirror
            Write-Ok 'payload 已复制回原仓库。'
        }

        if (-not $SkipInstaller) {
            $tempInstallerDir = Join-Path $workspaceRepo 'build\installer'
            if (-not (Test-Path -LiteralPath $tempInstallerDir)) {
                throw "临时构建没有生成安装器目录：$tempInstallerDir"
            }
            Copy-DirectoryTree -Source $tempInstallerDir `
                -Destination (Join-Path $RepoRoot 'build\installer') -Mirror
            Write-Ok '安装器 GUI 与运行库已复制回原仓库。'

            $tempBuildDir = Join-Path $workspaceRepo 'build'
            $tempSetups = @(Get-ChildItem -LiteralPath $tempBuildDir -Filter 'Sopeek-*.exe' `
                -File -ErrorAction SilentlyContinue)
            if ($tempSetups.Count -eq 0) {
                throw "临时构建没有生成最终安装包：$tempBuildDir\Sopeek-*.exe"
            }

            $destBuildDir = Join-Path $RepoRoot 'build'
            if (-not (Test-Path -LiteralPath $destBuildDir)) {
                New-Item -ItemType Directory -Force -Path $destBuildDir | Out-Null
            }
            foreach ($setup in $tempSetups) {
                $destSetup = Join-Path $destBuildDir $setup.Name
                Copy-Item -LiteralPath $setup.FullName -Destination $destSetup -Force
                $srcHash = (Get-FileHash -LiteralPath $setup.FullName -Algorithm SHA256).Hash
                $dstHash = (Get-FileHash -LiteralPath $destSetup -Algorithm SHA256).Hash
                if ($srcHash -ne $dstHash) {
                    throw "安装包复制校验失败：$destSetup"
                }
                Write-Ok ("安装包已复制并校验：$destSetup")
            }
        }

        $tempManifest = Join-Path $workspaceRepo 'build\release-manifest.json'
        if (-not (Test-Path -LiteralPath $tempManifest)) {
            throw "临时构建没有生成发布清单：$tempManifest"
        }
        $destManifest = $ManifestPath
        if ([string]::IsNullOrWhiteSpace($destManifest)) {
            $destManifest = Join-Path $RepoRoot 'build\release-manifest.json'
        }
        $destManifest = [System.IO.Path]::GetFullPath($destManifest)
        $manifestDir = Split-Path -Parent $destManifest
        if ($manifestDir -and -not (Test-Path -LiteralPath $manifestDir)) {
            New-Item -ItemType Directory -Force -Path $manifestDir | Out-Null
        }
        Copy-Item -LiteralPath $tempManifest -Destination $destManifest -Force
        Write-Ok ("发布清单已复制：$destManifest")

        $tempGate = Join-Path $workspaceRepo 'build\brand-gate.json'
        if (Test-Path -LiteralPath $tempGate) {
            Copy-Item -LiteralPath $tempGate `
                -Destination (Join-Path $RepoRoot 'build\brand-gate.json') -Force
        }

        $TotalWatch.Stop()
        Write-Host ''
        Write-Host '==================== BUILD SUMMARY (relocated) ====================' -ForegroundColor Cyan
        $summaryVersion = (Get-Content -LiteralPath $VersionFile -TotalCount 1).Trim()
        Write-Host ("  版本        : {0}" -f $summaryVersion)
        Write-Host ("  总耗时      : {0:N1} s" -f $TotalWatch.Elapsed.TotalSeconds)
        Write-Host ("  临时目录    : {0}" -f $workspace)
        if (-not $SkipInstaller) {
            $copiedSetups = @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'build') `
                -Filter 'Sopeek-*.exe' -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending)
            if ($copiedSetups.Count -gt 0) {
                $finalSetup = $copiedSetups[0]
                Write-Host ("  安装包      : {0}" -f $finalSetup.FullName)
                Write-Host ("  SHA256      : {0}" -f `
                    (Get-FileHash -LiteralPath $finalSetup.FullName -Algorithm SHA256).Hash)
            }
        } else {
            Write-Host ("  payload     : {0}" -f (Join-Path $PayloadRoot 'Sopeek.exe'))
        }
        Write-Host '====================================================================' -ForegroundColor Cyan
        Write-Host ''

        try {
            Remove-Item -LiteralPath $workspace -Recurse -Force -ErrorAction Stop
            Write-Ok '临时工作目录已清理。'
        } catch {
            Write-Warn ("临时目录清理失败，可手动删除：$workspace")
            Write-Note ("原因：$($_.Exception.Message)")
        }

        return 0
    } catch {
        Write-Host ''
        Write-Host ("BUILD FAILED: " + $_.Exception.Message) -ForegroundColor Red
        Write-Host ''
        if ($workspace -and (Test-Path -LiteralPath $workspace)) {
            Write-Host "临时工作目录已保留，便于排查。" -ForegroundColor Yellow
            Write-Host ("  {0}" -f $workspace) -ForegroundColor Yellow
            Write-Host ("排查完成后可删除：Remove-Item -LiteralPath '$workspace' -Recurse -Force") `
                -ForegroundColor DarkGray
        }
        return 1
    }
}

# ---------------------------------------------------------------------------
# 中文路径提示 + 打包契约检查（复制临时目录之前先 fail-fast）
# ---------------------------------------------------------------------------
$nonAsciiRepo = Test-NonAsciiPath -Path $RepoRoot
if ($nonAsciiRepo) {
    Write-Warn "仓库路径包含非 ASCII 字符（如中文）：$RepoRoot"
    Write-Note 'CMake + MinGW 不支持该路径；预检通过后会自动切换到纯英文临时目录继续构建。'
}

$contractFiles = New-Object System.Collections.Generic.List[string]
$contractFiles.Add($VersionFile)
if (-not $SkipPyInstaller) {
    $contractFiles.Add((Join-Path $RepoRoot 'packaging\build.py'))
    $contractFiles.Add((Join-Path $RepoRoot 'src\sopeek\app\main.py'))
}
if (-not $SkipInstaller) {
    $contractFiles.Add((Join-Path $RepoRoot 'packaging\installer\build.ps1'))
    $contractFiles.Add((Join-Path $RepoRoot 'packaging\installer\CMakeLists.txt'))
    $contractFiles.Add((Join-Path $RepoRoot 'packaging\installer\installer.nsi'))
}
$missingContract = @($contractFiles | Where-Object { -not (Test-Path -LiteralPath $_) })
if ($missingContract.Count -gt 0) {
    Fail ("缺少打包契约文件，项目结构可能已变更：`n  " + ($missingContract -join "`n  ")) 2
}

if ($SkipPyInstaller) {
    $existingPayloadExe = Join-Path $PayloadRoot 'Sopeek.exe'
    if (-not (Test-Path -LiteralPath $existingPayloadExe)) {
        Fail "已指定 -SkipPyInstaller，但现有 payload 缺少主程序：$existingPayloadExe（请先完整构建一次）" 2
    }
    if (-not (Test-Path -LiteralPath (Join-Path $PayloadRoot '_internal'))) {
        Fail "已指定 -SkipPyInstaller，但现有 payload 缺少 _internal 目录：$PayloadRoot" 2
    }
}

if (-not $SkipPyInstaller) {
    $preflightPython = Resolve-Python
    if (-not $preflightPython) {
        Fail '未找到 Python 解释器（.venv 或 PATH）。' 2
    }

    & $preflightPython -c "import PyInstaller" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail @"
当前 Python 环境缺少 PyInstaller，无法打包主程序。
Python：$preflightPython

请先安装依赖，例如：
  $preflightPython -m pip install -r requirements.txt
  $preflightPython -m pip install pyinstaller==6.22.3
"@ 2
    }

    & $preflightPython -c "import PySide6" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail @"
当前 Python 环境缺少 PySide6，无法打包主程序。
Python：$preflightPython

请先安装依赖：
  $preflightPython -m pip install -r requirements.txt
"@ 2
    }
}

if ($nonAsciiRepo -and -not $FromAsciiWorkspace) {
    $asciiExitCode = Invoke-AsciiWorkspaceBuild
    exit $asciiExitCode
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
            & $Python 'packaging/build.py' @PyInstallerArgs
        } else {
            & $Python 'packaging/build.py'
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

$payloadExeItem = Get-Item -LiteralPath $payloadExe
if ($payloadExeItem.Length -le 0) {
    Fail "payload 主程序为空文件：$payloadExe" 1
}
$payloadBytes = (Get-ChildItem -LiteralPath $PayloadRoot -Recurse -File |
    Measure-Object -Property Length -Sum).Sum
if ($null -eq $payloadBytes) { $payloadBytes = 0 }
if ($payloadBytes -le 0) {
    Fail "payload 目录为空：$PayloadRoot" 1
}
Write-Ok ("payload：{0:N1} MB" -f ($payloadBytes / 1MB))

# ---------------------------------------------------------------------------
# 2. 安装器构建（C++ GUI + NSIS）
# ---------------------------------------------------------------------------
Write-Step '2/4' '安装器构建（C++ GUI + NSIS）'

if ($SkipInstaller) {
    Write-Warn '已按 -SkipInstaller 跳过。'
} else {
    $installerScript = Join-Path $RepoRoot 'packaging\installer\build.ps1'
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
if (-not $SkipInstaller -and $SetupExe) {
    # 防止 NSIS 静默失败时把上一次的旧安装包当成本次产物。
    $setupItem = Get-Item -LiteralPath $SetupExe
    if ($setupItem.LastWriteTimeUtc -lt $BuildStartUtc) {
        Fail ("安装包不是本次构建生成的（最后写入 {0}）：{1}" -f `
            $setupItem.LastWriteTime, $SetupExe) 1
    }
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
# packaging/installer/build.ps1 计算后经 -D 传入）。字面量值若与 SPKVERSION 不一致就
# 提示；`${...}` 形式的宏引用属于正常情况，跳过。
$nsiPath = Join-Path $RepoRoot 'packaging\installer\installer.nsi'
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
    $gate = Join-Path $RepoRoot 'tools\verify_no_legacy_brand.ps1'
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
