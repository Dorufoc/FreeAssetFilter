<#
.SYNOPSIS
    Sopeek 打包垃圾清理：删除 build/、构建缓存与临时构建目录。

.DESCRIPTION
    默认删除整个 build/（payload、PyInstaller work、安装器 GUI、构建日志与最终
    安装包）以及仓库内的 Python/测试缓存。所有仓库内目标在删除前都会经过
    `git check-ignore` 校验：只有被 .gitignore 忽略的路径才会被删除，因此
    src/sopeek/core/native/bin/ 下随包分发的 dll/exe/pyd 等入库文件在机制上
    不可能被误删。

    仓库外的 C:\SopeekBuild_* 临时目录也会清理，但仅限 workspace.json 中
    sourceRepo 指向本仓库、所属进程已退出、且最后写入超过 1 小时的目录，
    不会影响正在进行的构建。

.PARAMETER Yes
    跳过确认提示。

.PARAMETER WhatIf
    只列出将删除的内容和大小，不执行任何删除。

.PARAMETER KeepSetup
    保留 build/Sopeek-*.exe（其余 build 内容照删），便于清理后继续测试安装包。

.PARAMETER Deep
    追加清理 native/*/target（Rust 编译缓存）、native/cpp_*/build、
    packaging/launcher 的启动器产物，以及 %LOCALAPPDATA%\pyinstaller 全局缓存。
    这些不是 packaging/build.py 直接产生的，默认保留。

.PARAMETER NoTemp
    不清理仓库外的 C:\SopeekBuild_* 临时构建目录。

.PARAMETER Kill
    发现 Sopeek / SopeekInstaller / SPK-Launcher 进程占用产物时直接结束，
    而不是中止并提示手动关闭。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools/clean_build.ps1 -WhatIf

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools/clean_build.ps1 -Yes -Deep
#>

param(
    [switch]$Yes,
    [switch]$WhatIf,
    [switch]$KeepSetup,
    [switch]$Deep,
    [switch]$NoTemp,
    [switch]$Kill
)

$ErrorActionPreference = 'Stop'

# 与 build.cmd / build_release.ps1 保持一致：控制台与管道统一 UTF-8，
# 避免中文路径和日志在 Windows PowerShell 5.1 下按 ANSI 误读。
try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = $utf8NoBom
    $OutputEncoding = $utf8NoBom
} catch { }

$ScriptDir = $PSScriptRoot
$RepoRoot = Split-Path -Parent $ScriptDir
$BuildDir = Join-Path $RepoRoot 'build'

# ---------------------------------------------------------------------------
# 输出辅助
# ---------------------------------------------------------------------------
function Write-Step {
    param([string]$Text)
    Write-Host ''
    Write-Host ('=' * 68) -ForegroundColor DarkGray
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('=' * 68) -ForegroundColor DarkGray
}

function Write-Ok {
    param([string]$Text)
    Write-Host ('  [OK] ' + $Text) -ForegroundColor Green
}

function Write-Note {
    param([string]$Text)
    Write-Host ('       ' + $Text) -ForegroundColor DarkGray
}

function Write-Warn {
    param([string]$Text)
    Write-Host ('  [!!] ' + $Text) -ForegroundColor Yellow
}

function Format-Size {
    param([int64]$Bytes)
    if ($Bytes -ge 1GB) { return ('{0:N2} GB' -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ('{0:N1} MB' -f ($Bytes / 1MB)) }
    if ($Bytes -ge 1KB) { return ('{0:N0} KB' -f ($Bytes / 1KB)) }
    return ('{0} B' -f $Bytes)
}

function Get-TreeSize {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($null -eq $item) { return [int64]0 }
    if (-not $item.PSIsContainer) { return [int64]$item.Length }
    $sum = (Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
    if ($null -eq $sum) { return [int64]0 }
    return [int64]$sum
}

# ---------------------------------------------------------------------------
# 预检：确认脚本位于仓库内，避免被复制到别处后误删无关目录。
# ---------------------------------------------------------------------------
$missing = @()
foreach ($marker in @('SPKVERSION', 'packaging\build.py')) {
    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot $marker))) { $missing += $marker }
}
if ($missing.Count -gt 0) {
    Write-Host ''
    Write-Host ('拒绝执行：当前目录不像 Sopeek 仓库根（缺少 ' + ($missing -join '、') + '）') -ForegroundColor Red
    Write-Host ('  推断根目录：' + $RepoRoot) -ForegroundColor Red
    exit 2
}

& git -C $RepoRoot rev-parse --is-inside-work-tree 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '拒绝执行：当前目录不是 git 工作区，无法执行 check-ignore 安全校验。' -ForegroundColor Red
    exit 2
}

# ---------------------------------------------------------------------------
# 收集清理目标
# ---------------------------------------------------------------------------
$targets = New-Object System.Collections.Generic.List[object]

function Add-Target {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label,
        [bool]$InRepo = $true
    )
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $targets.Add([pscustomobject]@{
        Path   = $Path
        Label  = $Label
        InRepo = $InRepo
    })
}

# 1. 仓库根 build/（默认整个删除；-KeepSetup 时保留最终安装包）
if (Test-Path -LiteralPath $BuildDir) {
    if ($KeepSetup) {
        foreach ($child in Get-ChildItem -LiteralPath $BuildDir -Force -ErrorAction SilentlyContinue) {
            if ((-not $child.PSIsContainer) -and ($child.Name -like 'Sopeek-*.exe')) { continue }
            Add-Target -Path $child.FullName -Label ('build/' + $child.Name)
        }
    } else {
        Add-Target -Path $BuildDir -Label 'build/'
    }
}

# 2. 安装器本地构建目录与运行期残留
Add-Target -Path (Join-Path $RepoRoot 'packaging\installer\build') -Label 'packaging/installer/build/'
Add-Target -Path (Join-Path $RepoRoot 'packaging\installer\install-result.ini') -Label 'packaging/installer/install-result.ini'

# 3. 测试 / lint 缓存
foreach ($rel in @('.ruff_cache', '.pytest_cache', '.mypy_cache', 'tests\log', 'test_results', 'htmlcov')) {
    Add-Target -Path (Join-Path $RepoRoot $rel) -Label $rel
}
foreach ($pattern in @('.coverage', '.coverage.*', 'coverage.xml', 'cov_*.json')) {
    foreach ($file in Get-ChildItem -LiteralPath $RepoRoot -Filter $pattern -File -Force -ErrorAction SilentlyContinue) {
        Add-Target -Path $file.FullName -Label $file.Name
    }
}

# 4. 仓库根残留的构建描述文件与原生编译中间文件（launcher 用 cl.exe 在根目录
#    生成 .obj；PyInstaller 生成的 .spec 也落在根目录）。
foreach ($pattern in @('*.spec', '*.obj', '*.pdb', '*.ilk', '*.exp')) {
    foreach ($file in Get-ChildItem -LiteralPath $RepoRoot -Filter $pattern -File -Force -ErrorAction SilentlyContinue) {
        Add-Target -Path $file.FullName -Label $file.Name
    }
}

# 5. .venv / .git / build / target 之外的 __pycache__
$cacheDirs = @(Get-ChildItem -LiteralPath $RepoRoot -Recurse -Directory -Filter '__pycache__' -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '[\\/](\.venv|\.git|build|node_modules|target)[\\/]' })
foreach ($dir in $cacheDirs) {
    $rel = $dir.FullName.Substring($RepoRoot.Length + 1)
    Add-Target -Path $dir.FullName -Label $rel
}
if ($cacheDirs.Count -gt 0) {
    Write-Note ('发现 __pycache__：{0} 处（.venv 内已排除）' -f $cacheDirs.Count)
}

# 6. -Deep：原生构建缓存与启动器产物（不是一次打包的必然产物）
if ($Deep) {
    $nativeRoot = Join-Path $RepoRoot 'native'
    if (Test-Path -LiteralPath $nativeRoot) {
        foreach ($crate in Get-ChildItem -LiteralPath $nativeRoot -Directory -Force -ErrorAction SilentlyContinue) {
            Add-Target -Path (Join-Path $crate.FullName 'target') -Label ('native/' + $crate.Name + '/target/')
        }
        foreach ($crate in Get-ChildItem -LiteralPath $nativeRoot -Directory -Filter 'cpp_*' -Force -ErrorAction SilentlyContinue) {
            Add-Target -Path (Join-Path $crate.FullName 'build') -Label ('native/' + $crate.Name + '/build/')
        }
    }
    $launcherDir = Join-Path $RepoRoot 'packaging\launcher'
    if (Test-Path -LiteralPath $launcherDir) {
        foreach ($file in Get-ChildItem -LiteralPath $launcherDir -File -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like 'SPK-Launcher.*' -or $_.Extension -in @('.obj', '.res') }) {
            Add-Target -Path $file.FullName -Label ('packaging/launcher/' + $file.Name)
        }
    }
    if ($env:LOCALAPPDATA) {
        $pyinstallerCache = Join-Path $env:LOCALAPPDATA 'pyinstaller'
        if (Test-Path -LiteralPath $pyinstallerCache) {
            Add-Target -Path $pyinstallerCache -Label $pyinstallerCache -InRepo $false
        }
    }
}

# 7. 仓库外的 <盘符>:\SopeekBuild_* 临时工作区（中文仓库路径触发的镜像构建）。
if (-not $NoTemp) {
    foreach ($drive in [System.IO.DriveInfo]::GetDrives()) {
        if ($drive.DriveType -ne [System.IO.DriveType]::Fixed -or -not $drive.IsReady) { continue }
        $workspaces = @(Get-ChildItem -LiteralPath $drive.RootDirectory.FullName -Directory -Filter 'SopeekBuild_*' -Force -ErrorAction SilentlyContinue)
        foreach ($workspace in $workspaces) {
            $settingsPath = Join-Path $workspace.FullName 'workspace.json'
            if (-not (Test-Path -LiteralPath $settingsPath)) { continue }
            try {
                $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
            } catch {
                continue
            }
            if ([string]$settings.sourceRepo -ne $RepoRoot) { continue }

            # 保护正在进行的构建：进程仍存活、或目录最近 1 小时内仍有写入。
            if ($null -ne $settings.processId) {
                try {
                    if (Get-Process -Id ([int]$settings.processId) -ErrorAction SilentlyContinue) { continue }
                } catch { }
            }
            if ($workspace.LastWriteTime -gt (Get-Date).AddHours(-1)) { continue }

            Add-Target -Path $workspace.FullName -Label $workspace.FullName -InRepo $false
        }
    }
}

# ---------------------------------------------------------------------------
# 安全校验：仓库内目标必须被 .gitignore 命中，否则跳过。
# ---------------------------------------------------------------------------
$invalid = New-Object System.Collections.Generic.List[string]
$checked = New-Object System.Collections.Generic.List[object]
foreach ($target in $targets) {
    if ($target.InRepo) {
        $rel = $target.Path.Substring($RepoRoot.Length + 1).Replace('\', '/')
        & git -C $RepoRoot check-ignore -q -- $rel 2>$null
        if ($LASTEXITCODE -ne 0) {
            $invalid.Add($target.Label)
            continue
        }
    }
    $target | Add-Member -NotePropertyName Size -NotePropertyValue (Get-TreeSize -Path $target.Path) -Force
    $checked.Add($target)
}
$targets = $checked

if ($invalid.Count -gt 0) {
    Write-Warn '以下路径未被 .gitignore 忽略，已跳过（防止误删入库文件）：'
    foreach ($item in $invalid) { Write-Note $item }
}

if ($targets.Count -eq 0) {
    Write-Host ''
    Write-Ok '没有需要清理的产物，仓库已经是干净状态。'
    exit 0
}

# ---------------------------------------------------------------------------
# 占用检测：payload 里的 Sopeek.exe 正在运行时删除会失败。
# ---------------------------------------------------------------------------
$running = New-Object System.Collections.Generic.List[object]
foreach ($name in @('Sopeek', 'SopeekInstaller', 'SPK-Launcher')) {
    foreach ($proc in Get-Process -Name $name -ErrorAction SilentlyContinue) {
        try { $procPath = $proc.Path } catch { $procPath = $null }
        if ($procPath -and $procPath.StartsWith($RepoRoot, [StringComparison]::OrdinalIgnoreCase)) {
            $running.Add([pscustomobject]@{ Process = $proc; Path = $procPath })
        }
    }
}
if ($running.Count -gt 0) {
    if ($Kill) {
        foreach ($item in $running) {
            try {
                Stop-Process -Id $item.Process.Id -Force -ErrorAction Stop
                Write-Warn ('已结束进程：{0} (pid {1})' -f $item.Process.ProcessName, $item.Process.Id)
            } catch {
                Write-Warn ('无法结束进程 {0} (pid {1})：{2}' -f $item.Process.ProcessName, $item.Process.Id, $_.Exception.Message)
            }
        }
        Start-Sleep -Milliseconds 500
    } else {
        Write-Host ''
        Write-Host '检测到以下进程正在使用仓库内的产物，请先关闭后重试（或加 -Kill）：' -ForegroundColor Red
        foreach ($item in $running) {
            Write-Host ('  {0} (pid {1})  {2}' -f $item.Process.ProcessName, $item.Process.Id, $item.Path) -ForegroundColor Red
        }
        exit 1
    }
}

# ---------------------------------------------------------------------------
# 展示与确认
# ---------------------------------------------------------------------------
$totalBytes = [int64]0
foreach ($target in $targets) { $totalBytes += $target.Size }

Write-Step '将清理以下产物'
foreach ($target in $targets) {
    Write-Host ('  {0,-46} {1,10}' -f $target.Label, (Format-Size $target.Size))
}
Write-Host ''
Write-Host ('  合计：' + (Format-Size $totalBytes)) -ForegroundColor Yellow

if ($WhatIf) {
    Write-Host ''
    Write-Ok '预览完成（-WhatIf）：未删除任何文件。'
    exit 0
}

if (-not $Yes) {
    $answer = Read-Host '确认删除以上内容？输入 Y 继续'
    if ($answer -notmatch '^(y|yes)$') {
        Write-Host ''
        Write-Host '已取消。' -ForegroundColor Yellow
        exit 0
    }
}

# ---------------------------------------------------------------------------
# 删除（Remove-Item -> .NET -> rd 三级降级，尽量吃掉占用/只读/长路径）
# ---------------------------------------------------------------------------
function Remove-PathRobust {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $true }

    for ($attempt = 0; $attempt -lt 2; $attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return $true
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }

    try {
        $full = [System.IO.Path]::GetFullPath($Path)
        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            [System.IO.File]::SetAttributes($full, [System.IO.FileAttributes]::Normal)
            [System.IO.File]::Delete($full)
        } else {
            [System.IO.Directory]::Delete($full, $true)
        }
        if (-not (Test-Path -LiteralPath $Path)) { return $true }
    } catch { }

    try {
        & cmd.exe /c ('rd /s /q "' + $Path + '"') 2>$null | Out-Null
        return (-not (Test-Path -LiteralPath $Path))
    } catch {
        return $false
    }
}

$statusBefore = @(& git -C $RepoRoot status --porcelain 2>$null)

Write-Step '开始清理'
$freedBytes = [int64]0
$deleted = 0
$failed = New-Object System.Collections.Generic.List[string]

foreach ($target in $targets) {
    $ok = Remove-PathRobust -Path $target.Path
    if ($ok) {
        $deleted += 1
        $freedBytes += $target.Size
        Write-Host ('  [del] {0,-46} {1,10}' -f $target.Label, (Format-Size $target.Size)) -ForegroundColor DarkGray
    } else {
        $failed.Add($target.Label)
        Write-Warn ('删除失败：' + $target.Label)
    }
}

# -KeepSetup 删除子项后，build/ 若已空则一并移除。
if ($KeepSetup -and (Test-Path -LiteralPath $BuildDir)) {
    $left = @(Get-ChildItem -LiteralPath $BuildDir -Force -ErrorAction SilentlyContinue)
    if ($left.Count -eq 0) {
        try { Remove-Item -LiteralPath $BuildDir -Recurse -Force -ErrorAction Stop } catch { }
    } else {
        Write-Note ('build/ 保留内容：' + (($left | ForEach-Object { $_.Name }) -join ', '))
    }
}

# ---------------------------------------------------------------------------
# 汇总与事后校验
# ---------------------------------------------------------------------------
Write-Step '清理结果'
Write-Host ('  删除条目：{0}' -f $deleted)
Write-Host ('  释放空间：' + (Format-Size $freedBytes)) -ForegroundColor Green
if ($failed.Count -gt 0) {
    Write-Host ''
    Write-Host '以下条目未能删除（可能被占用或无权限）：' -ForegroundColor Red
    foreach ($item in $failed) { Write-Host ('  - ' + $item) -ForegroundColor Red }
}

$statusAfter = @(& git -C $RepoRoot status --porcelain 2>$null)
Write-Host ''
if ($statusAfter.Count -eq $statusBefore.Count) {
    Write-Ok ('git status 无新增改动（当前工作区改动 {0} 项，均为清理前已存在）' -f $statusAfter.Count)
} else {
    Write-Warn ('git status 改动数由 {0} 变为 {1}，请检查是否有入库文件被删除！' -f $statusBefore.Count, $statusAfter.Count)
}

if (-not $KeepSetup) {
    Write-Note '最终安装包已删除；重新测试安装流程请先运行 build.cmd 重新打包。'
}
if ($Deep) {
    Write-Note '已包含 -Deep：原生 target 与全局缓存已清理，下次原生构建需要全量重编。'
}

if ($failed.Count -gt 0) { exit 1 }
exit 0
