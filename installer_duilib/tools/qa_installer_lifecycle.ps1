<#
T20 installer lifecycle QA.

Runs only the FAF_TESTMODE setup (FreeAssetFilterTest paths) and only against
test artifacts. Never invokes production setup/uninstaller entries.

Modes: fresh | repair | cancel | second-instance | uninstall | failure |
       shortcut-isolation | uac-cancel | all
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('fresh', 'repair', 'cancel', 'second-instance', 'uninstall', 'failure', 'shortcut-isolation', 'uac-cancel', 'all')]
    [string]$Mode,

    [string]$SetupPath = 'build/test-installer/FreeAssetFilter_NSIS_Test.exe',
    [string]$EvidenceDir = '.omo/evidence/installer-repair-uninstall/t20',
    [switch]$Keep
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$SetupPath = (Resolve-Path (Join-Path $RepoRoot $SetupPath)).Path
$EvidenceDir = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $EvidenceDir))
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null

$TestInstallDir = Join-Path $env:LOCALAPPDATA 'FreeAssetFilterTest'
$TestUninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest'
$TestAppKey = 'HKCU:\Software\FreeAssetFilterTest'
$CanonicalDataDir = Join-Path $env:LOCALAPPDATA 'FreeAssetFilterTestUserData'
$CustomDataDir = Join-Path $env:LOCALAPPDATA 'FreeAssetFilterTestFafData'
$DesktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'FreeAssetFilterTest.lnk'
$StartMenuShortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'FreeAssetFilterTest.lnk'
$TranscriptPath = Join-Path $EvidenceDir 'transcript.log'
$SummaryPath = Join-Path $EvidenceDir 'summary.json'

$script:Results = [System.Collections.Generic.List[object]]::new()
$script:CurrentDiag = $null
# M1: only temp paths created/tracked by this QA run may ever be deleted.
$script:CreatedTempDirs = [System.Collections.Generic.List[string]]::new()

function Write-Log([string]$Message, [string]$Level = 'INFO') {
    $line = '[{0}] {1,-5} {2}' -f (Get-Date -Format 'HH:mm:ss.fff'), $Level, $Message
    Write-Host $line
    Add-Content -LiteralPath $TranscriptPath -Value $line -Encoding utf8
}

function Add-Result([string]$Name, [string]$Status, [string]$Detail = '') {
    $script:Results.Add([pscustomobject]@{ name = $Name; status = $Status; detail = $Detail })
    Write-Log "$Name => $Status $Detail" $(if ($Status -eq 'PASS') { 'INFO' } elseif ($Status -eq 'SKIP') { 'WARN' } else { 'ERROR' })
}

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "ASSERTION FAILED: $Message" }
    Write-Log "assert ok: $Message"
}

function Assert-UnderTestRoot([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    $allowed = @(
        [System.IO.Path]::GetFullPath($TestInstallDir),
        [System.IO.Path]::GetFullPath($CanonicalDataDir),
        [System.IO.Path]::GetFullPath($CustomDataDir),
        [System.IO.Path]::GetFullPath((Join-Path $env:TEMP 'opencode'))
    )
    foreach ($root in $allowed) {
        if ($full.Equals($root, [StringComparison]::OrdinalIgnoreCase) -or
            $full.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            return
        }
    }
    throw "REFUSING destructive operation outside test roots: $full"
}

# M1 destructive-cleanup guard. Deliberately separate from Assert-UnderTestRoot:
# %TEMP%\FreeAssetFilterMaintenance-<digits> is neither under the test install
# dir nor under %TEMP%\opencode. Cleanup is allowed only for the exact leaf shape
# whose parent is exactly %TEMP% (never %TEMP% itself, never a production copy
# that this run did not register).
function Assert-MaintenanceTempPath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    $tempRoot = [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $parent = [System.IO.Path]::GetDirectoryName($full)
    $leaf = [System.IO.Path]::GetFileName($full)
    if ([string]::IsNullOrEmpty($parent) -or
        -not [string]::Equals($parent.TrimEnd([System.IO.Path]::DirectorySeparatorChar), $tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "REFUSING temp cleanup outside %TEMP%: $full"
    }
    if ($leaf -notmatch '^FreeAssetFilterMaintenance-\d+$') {
        throw "REFUSING temp cleanup with unexpected leaf: $full"
    }
    if ($full.Equals($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "REFUSING temp cleanup of %TEMP% itself: $full"
    }
}

function Register-MaintenanceTempPath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    Assert-MaintenanceTempPath $full
    if (-not $script:CreatedTempDirs.Contains($full)) { $script:CreatedTempDirs.Add($full) }
}

function Remove-TestState {
    foreach ($p in @($TestInstallDir, $CanonicalDataDir, $CustomDataDir)) {
        Assert-UnderTestRoot $p
        if (Test-Path -LiteralPath $p) {
            Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    foreach ($k in @($TestUninstallKey, $TestAppKey)) {
        if (Test-Path -LiteralPath $k) { Remove-Item -LiteralPath $k -Recurse -Force -ErrorAction SilentlyContinue }
    }
    foreach ($s in @($DesktopShortcut, $StartMenuShortcut)) {
        if (Test-Path -LiteralPath $s) { Remove-Item -LiteralPath $s -Force -ErrorAction SilentlyContinue }
    }
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and ($_.ExecutablePath -like "$env:TEMP\~nsu*" -or $_.ExecutablePath -like "$env:TEMP\*FreeAssetFilter*") } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-Process -Name 'FreeAssetFilterInstaller', 'FreeAssetFilterUninstall', 'UninstallHelper', 'FreeAssetFilter', 'Un', 'Au_' -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($TestInstallDir, [StringComparison]::OrdinalIgnoreCase) } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 300
    # M1: remove only maintenance temp dirs this run registered, after their
    # exact %TEMP%\FreeAssetFilterMaintenance-<digits> shape is re-validated.
    foreach ($p in @($script:CreatedTempDirs)) {
        Assert-MaintenanceTempPath $p
        if (Test-Path -LiteralPath $p) {
            Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    $script:CreatedTempDirs.Clear()
}

function Invoke-WithRetry([scriptblock]$Action, [int]$Attempts = 5) {
    for ($i = 1; $i -le $Attempts; $i++) {
        try { & $Action; return } catch {
            if ($i -eq $Attempts) { throw }
            Start-Sleep -Milliseconds (250 * $i)
        }
    }
}

Add-Type -AssemblyName System.Drawing
if (-not ('T20Native' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class T20Native {
    public delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder sb, int n);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern IntPtr GetDC(IntPtr h);
    [DllImport("user32.dll")] public static extern int ReleaseDC(IntPtr h, IntPtr dc);
    [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleDC(IntPtr dc);
    [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleBitmap(IntPtr dc, int w, int h);
    [DllImport("gdi32.dll")] public static extern IntPtr SelectObject(IntPtr dc, IntPtr obj);
    [DllImport("gdi32.dll")] public static extern bool BitBlt(IntPtr dst, int x, int y, int w, int h, IntPtr src, int sx, int sy, int rop);
    [DllImport("gdi32.dll")] public static extern bool DeleteObject(IntPtr obj);
    [DllImport("gdi32.dll")] public static extern bool DeleteDC(IntPtr dc);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
'@
}

function Get-InstallWindows([int]$ProcessId = 0) {
    $script:InstallWindows = [System.Collections.Generic.List[object]]::new()
    $cb = [T20Native+EnumProc]{
        param($h, $l)
        $sb = [System.Text.StringBuilder]::new(256)
        [void][T20Native]::GetClassNameW($h, $sb, 256)
        if ($sb.ToString() -eq 'FreeAssetFilterInstaller' -and [T20Native]::IsWindowVisible($h)) {
            [uint32]$ownerPid = 0
            [void][T20Native]::GetWindowThreadProcessId($h, [ref]$ownerPid)
            if ($ProcessId -eq 0 -or $ownerPid -eq $ProcessId) {
                $script:InstallWindows.Add([pscustomobject]@{ Hwnd = $h; ProcessId = $ownerPid })
            }
        }
        return $true
    }
    [void][T20Native]::EnumWindows($cb, [IntPtr]::Zero)
    return @($script:InstallWindows)
}

function Get-InstallWindow([int]$ProcessId = 0) {
    $found = [IntPtr]::Zero
    $cb = [T20Native+EnumProc]{
        param($h, $l)
        $sb = [System.Text.StringBuilder]::new(256)
        [void][T20Native]::GetClassNameW($h, $sb, 256)
        if ($sb.ToString() -eq 'FreeAssetFilterInstaller' -and [T20Native]::IsWindowVisible($h)) {
            [uint32]$ownerPid = 0
            [void][T20Native]::GetWindowThreadProcessId($h, [ref]$ownerPid)
            if ($ProcessId -eq 0 -or $ownerPid -eq $ProcessId) {
                $script:FoundWindow = $h
                return $false
            }
        }
        return $true
    }
    $script:FoundWindow = [IntPtr]::Zero
    [void][T20Native]::EnumWindows($cb, [IntPtr]::Zero)
    return $script:FoundWindow
}

function Wait-InstallWindow([int]$ProcessId = 0, [int]$TimeoutSec = 45) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        $h = Get-InstallWindow $ProcessId
        if ($h -ne [IntPtr]::Zero) { return $h }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw "installer window not found within ${TimeoutSec}s (pid=$ProcessId)"
}

function Wait-Diag([string]$Path, [string]$Pattern, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        if (Test-Path -LiteralPath $Path) {
            $hit = Select-String -LiteralPath $Path -Pattern $Pattern -SimpleMatch -Quiet
            if ($hit) { return $true }
        }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Save-WindowPng([IntPtr]$Hwnd, [string]$Path) {
    $minimized = [System.Collections.Generic.List[IntPtr]]::new()
    $targets = @('WindowsTerminal', 'Trae CN', 'Code', 'pwsh', 'powershell', 'conhost', 'cmd')
    foreach ($proc in @(Get-Process -ErrorAction SilentlyContinue)) {
        if ($proc.MainWindowHandle -eq [IntPtr]::Zero -or $proc.MainWindowHandle -eq $Hwnd) { continue }
        if ($targets -notcontains $proc.ProcessName) { continue }
        [void][T20Native]::ShowWindow($proc.MainWindowHandle, 6)
        $minimized.Add($proc.MainWindowHandle)
    }
    if ($minimized.Count -gt 0) { Start-Sleep -Milliseconds 500 }
    try {
        [void][T20Native]::SetWindowPos($Hwnd, [IntPtr](-1), 0, 0, 0, 0, 0x0043)
        [void][T20Native]::SetForegroundWindow($Hwnd)
        Start-Sleep -Milliseconds 700
        $r = [T20Native+RECT]::new()
        if (-not [T20Native]::GetWindowRect($Hwnd, [ref]$r)) { throw 'GetWindowRect failed' }
        $dpi = [T20Native]::GetDpiForWindow($Hwnd)
        $scale = if ($dpi -ge 96) { $dpi / 96.0 } else { 1.0 }
        $sx = [int][Math]::Round($r.Left * $scale)
        $sy = [int][Math]::Round($r.Top * $scale)
        $w = [int][Math]::Round(($r.Right - $r.Left) * $scale)
        $h = [int][Math]::Round(($r.Bottom - $r.Top) * $scale)
        if ($w -le 0 -or $h -le 0) { throw "invalid window rect ${w}x${h}" }
        Write-Log "capture hwnd=$Hwnd rect=$($r.Left),$($r.Top),$($r.Right),$($r.Bottom) dpi=$dpi scale=$scale physical=${sx},${sy} size=${w}x${h}"
        $screen = [T20Native]::GetDC([IntPtr]::Zero)
        $mem = [T20Native]::CreateCompatibleDC($screen)
        $bmp = [T20Native]::CreateCompatibleBitmap($screen, $w, $h)
        $old = [T20Native]::SelectObject($mem, $bmp)
        try {
            if (-not [T20Native]::BitBlt($mem, 0, 0, $w, $h, $screen, $sx, $sy, 0x40CC0020)) {
                throw 'BitBlt from desktop DC failed'
            }
            $image = [System.Drawing.Image]::FromHbitmap($bmp)
            try { $image.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png) } finally { $image.Dispose() }
        } finally {
            [void][T20Native]::SelectObject($mem, $old)
            [void][T20Native]::DeleteObject($bmp)
            [void][T20Native]::DeleteDC($mem)
            [void][T20Native]::ReleaseDC([IntPtr]::Zero, $screen)
        }
        Assert-True (Test-Path -LiteralPath $Path) "screenshot saved: $Path"
    } finally {
        foreach ($m in $minimized) { [void][T20Native]::ShowWindow($m, 9) }
    }
}

function Close-InstallWindow([IntPtr]$Hwnd, [System.Diagnostics.Process]$Process) {
    [void][T20Native]::PostMessageW($Hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
    if (-not $Process.WaitForExit(30000)) {
        try { $Process.Kill($true) } catch {}
        throw "installer process $($Process.Id) did not exit after WM_CLOSE"
    }
}

function Start-TestSetup([string]$Tag, [string]$InstallOpts = $null, [string]$MaintenanceExtra = $null, [string]$UiExtra = $null) {
    $diag = Join-Path $EvidenceDir "$Tag.diag.log"
    Remove-Item -LiteralPath $diag -Force -ErrorAction SilentlyContinue
    $env:FAF_DIAG_PATH = $diag
    if ($null -ne $InstallOpts) { $env:FAF_QA_INSTALL_OPTS = $InstallOpts } else { Remove-Item Env:\FAF_QA_INSTALL_OPTS -ErrorAction SilentlyContinue }
    if ($null -ne $MaintenanceExtra) { $env:FAF_QA_MAINTENANCE_EXTRA = $MaintenanceExtra } else { Remove-Item Env:\FAF_QA_MAINTENANCE_EXTRA -ErrorAction SilentlyContinue }
    if (-not [string]::IsNullOrWhiteSpace($UiExtra)) { $env:FAF_QA_UI_RUNTIME_EXTRA = $UiExtra } else { Remove-Item Env:\FAF_QA_UI_RUNTIME_EXTRA -ErrorAction SilentlyContinue }
    $p = Start-Process -FilePath $SetupPath -PassThru
    $script:CurrentDiag = $diag
    return $p
}

function Start-TestUninstaller([string]$Tag, [int]$DeleteUserData, [string]$UiExtra = $null) {
    $helper = Join-Path $TestInstallDir 'UninstallHelper.exe'
    $ui = Join-Path $TestInstallDir 'FreeAssetFilterUninstall.exe'
    Assert-True (Test-Path -LiteralPath $helper) "test uninstall helper exists: $helper"
    Assert-True (Test-Path -LiteralPath $ui) "test uninstaller UI exists: $ui"
    $diag = Join-Path $EvidenceDir "$Tag.diag.log"
    Remove-Item -LiteralPath $diag -Force -ErrorAction SilentlyContinue
    $env:FAF_DIAG_PATH = $diag
    if (-not [string]::IsNullOrWhiteSpace($UiExtra)) { $env:FAF_QA_UI_RUNTIME_EXTRA = $UiExtra } else { $env:FAF_QA_UI_RUNTIME_EXTRA = "/auto:mode=uninstall /auto:action=uninstall /auto:delete-user-data=$DeleteUserData" }
    Remove-Item Env:\FAF_QA_INSTALL_OPTS -ErrorAction SilentlyContinue
    Remove-Item Env:\FAF_QA_MAINTENANCE_EXTRA -ErrorAction SilentlyContinue
    $p = Start-Process -FilePath $helper -ArgumentList @('/uninstall-launcher','/installdir',"$TestInstallDir",'/ui',"$ui") -PassThru
    Write-Log "uninstall env extra=$($env:FAF_QA_UI_RUNTIME_EXTRA)"
    Start-Sleep -Seconds 3
    $uiProc = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'FreeAssetFilterUninstall.exe' } | Select-Object -First 1
    if ($uiProc) { Write-Log "uninstall UI cmdline=$($uiProc.CommandLine)" } else { Write-Log 'uninstall UI not started yet' 'WARN' }
    $script:CurrentDiag = $diag
    return $p
}

function Complete-FinishPage([string]$Tag, [System.Diagnostics.Process]$Process) {
    Assert-True (Wait-Diag $script:CurrentDiag 'auto drive complete page=4' 120) "$Tag reached Finish (auto drive complete page=4)"
    # NSIS launches the GUI from a temp copy; its PID differs from the setup PID.
    $hwnd = Wait-InstallWindow 0 20
    Save-WindowPng $hwnd (Join-Path $EvidenceDir "$Tag-finish.png")
    Close-InstallWindow $hwnd $Process
    Write-Log "$Tag exit code=$($Process.ExitCode)"
    return $Process.ExitCode
}

function Read-IniValue([string]$Path, [string]$Section, [string]$Key) {
    $inSection = $false
    foreach ($line in Get-Content -LiteralPath $Path) {
        $t = $line.Trim()
        if ($t -match '^\[(.+)\]$') { $inSection = ($Matches[1] -eq $Section); continue }
        if ($inSection -and $t -match '^([^=]+)=(.*)$' -and $Matches[1].Trim() -eq $Key) { return $Matches[2].Trim() }
    }
    return $null
}

function Get-ProductionShortcutSnapshot([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ exists = $false }
    }
    $f = Get-Item -LiteralPath $Path
    return [ordered]@{
        exists = $true
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
        size = $f.Length
        mtime = $f.LastWriteTimeUtc.ToString('o')
    }
}

function Snapshot-Production {
    $items = [ordered]@{}
    $artifacts = @(
        'build/installer/FreeAssetFilterInstaller.exe',
        'build/installer/libwinpthread-1.dll',
        'build/FreeAssetFilter_NSIS_Setup.exe'
    )
    foreach ($rel in $artifacts) {
        $p = Join-Path $RepoRoot $rel
        if (Test-Path -LiteralPath $p) {
            $f = Get-Item -LiteralPath $p
            $items[$rel] = @{
                sha256 = (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash
                size = $f.Length
                mtime = $f.LastWriteTimeUtc.ToString('o')
            }
        } else { $items[$rel] = 'MISSING' }
    }
    $keys = @(
        'HKCU:\Software\FreeAssetFilter',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter',
        'HKLM:\Software\FreeAssetFilter',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter',
        'HKLM:\Software\WOW6432Node\FreeAssetFilter',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter'
    )
    foreach ($k in $keys) { $items["reg:$k"] = (Test-Path -LiteralPath $k) }
    $items['prodDirExists'] = (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'FreeAssetFilter'))
    # D13/F2: production shortcuts are part of the guard. Hash/size/mtime detect
    # overwrite/delete even when a shortcut is recreated at the same path.
    $desktop = [Environment]::GetFolderPath('Desktop')
    $programs = [Environment]::GetFolderPath('Programs')
    $prodStartMenuFolder = Join-Path $programs 'FreeAssetFilter'
    $items['startMenuProdFolderExists'] = (Test-Path -LiteralPath $prodStartMenuFolder)
    $items['desktopProdShortcut'] = Get-ProductionShortcutSnapshot (Join-Path $desktop 'FreeAssetFilter.lnk')
    $items['startMenuProdShortcutFolder'] = Get-ProductionShortcutSnapshot (Join-Path $prodStartMenuFolder 'FreeAssetFilter.lnk')
    $items['startMenuProdShortcutLegacy'] = Get-ProductionShortcutSnapshot (Join-Path $programs 'FreeAssetFilter.lnk')
    return ($items | ConvertTo-Json -Depth 6 -Compress)
}

function Install-Fresh([string]$Tag = 'fresh') {
    Write-Log '--- fresh install ---'
    Remove-TestState
    $before = Snapshot-Production
    Set-Content -LiteralPath (Join-Path $EvidenceDir 'production-before.json') -Value $before -Encoding utf8
    $p = Start-TestSetup $Tag -InstallOpts '0000'
    $code = Complete-FinishPage $Tag $p
    Assert-True ($code -eq 0) "$Tag setup exit code 0 (actual $code)"
    Assert-True (Test-Path -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilter.exe')) 'app exe installed'
    Assert-True (Test-Path -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilterUninstall.exe')) 'uninstaller installed'
    Assert-True (Test-Path -LiteralPath (Join-Path $TestInstallDir 'UninstallHelper.exe')) 'UninstallHelper installed'
    Assert-True (Test-Path -LiteralPath $TestUninstallKey) 'test uninstall registry key exists'
    Assert-True (-not (Test-Path -LiteralPath $DesktopShortcut)) 'options=0000: no test desktop shortcut'
    Assert-True (-not (Test-Path -LiteralPath $StartMenuShortcut)) 'options=0000: no test start-menu shortcut'
    $after = Snapshot-Production
    Assert-True ($before -eq $after) 'production artifacts/keys/shortcuts unchanged after fresh install'
    Add-Result 'fresh' 'PASS' 'install, registry, no shortcuts, production untouched'
}

function Ensure-Installed {
    if (-not (Test-Path -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilter.exe'))) { Install-Fresh 'fresh' }
}

function Test-Repair {
    Write-Log '--- repair ---'
    Ensure-Installed
    $before = Snapshot-Production
    $appExe = Join-Path $TestInstallDir 'FreeAssetFilter.exe'
    $h = (Get-FileHash -LiteralPath $appExe -Algorithm SHA256).Hash
    $dataDir = Join-Path $TestInstallDir 'data'
    New-Item -ItemType Directory -Force -Path $dataDir, $CanonicalDataDir | Out-Null
    Set-Content -LiteralPath (Join-Path $dataDir 'repair-sentinel.txt') -Value 'data-preserved' -Encoding utf8
    Set-Content -LiteralPath (Join-Path $CanonicalDataDir 'repair-sentinel.txt') -Value 'canonical-preserved' -Encoding utf8
    Remove-Item -LiteralPath $appExe -Force
    Assert-True (-not (Test-Path -LiteralPath $appExe)) 'injected damage: app exe deleted before repair'
    $p = Start-TestSetup 'repair' -MaintenanceExtra '/auto:action=repair'
    $code = Complete-FinishPage 'repair' $p
    Assert-True ($code -eq 0) "repair setup exit code 0 (actual $code)"
    Assert-True (Test-Path -LiteralPath $appExe) 'repair restored app exe'
    Assert-True (Test-Path -LiteralPath $TestUninstallKey) 'repair kept uninstall key'
    $h2 = (Get-FileHash -LiteralPath $appExe -Algorithm SHA256).Hash
    Assert-True ($h2 -eq $h) "repair restored app exe bytes (expected $h, actual $h2)"
    Assert-True (Test-Path -LiteralPath (Join-Path $dataDir 'repair-sentinel.txt')) 'repair preserved install data sentinel'
    Assert-True (Test-Path -LiteralPath (Join-Path $CanonicalDataDir 'repair-sentinel.txt')) 'repair preserved canonical data sentinel'
    Assert-True (-not (Test-Path -LiteralPath $DesktopShortcut)) 'repair kept options=0000: no desktop shortcut'
    Assert-True (-not (Test-Path -LiteralPath $StartMenuShortcut)) 'repair kept options=0000: no start-menu shortcut'
    $after = Snapshot-Production
    Assert-True ($before -eq $after) 'production artifacts/keys/shortcuts unchanged after repair'
    Add-Result 'repair' 'PASS' 'finish screenshot captured; exit 0; options/shortcuts unchanged'
}

function Test-Cancel {
    Write-Log '--- maintenance cancel ---'
    Ensure-Installed
    $before = Snapshot-Production
    $p = Start-TestSetup 'cancel' -MaintenanceExtra '/auto:action=cancel /auto:page=6'
    if (-not $p.WaitForExit(90000)) {
        $h = Get-InstallWindow $p.Id
        if ($h -ne [IntPtr]::Zero) { Close-InstallWindow $h $p } else { try { $p.Kill($true) } catch {} }
        throw 'cancel setup did not exit within 90s'
    }
    Write-Log "cancel exit code=$($p.ExitCode)"
    Assert-True ($p.ExitCode -ne 0) "cancel exits nonzero (actual $($p.ExitCode))"
    $decision = Join-Path $TestInstallDir 'maintenance-decision.ini'
    Assert-True (Test-Path -LiteralPath $decision) 'maintenance-decision.ini exists'
    Assert-True ((Read-IniValue $decision 'maintenance' 'action') -eq 'cancel') 'decision action=cancel'
    Assert-True ((Read-IniValue $decision 'maintenance' 'ack') -eq '1') 'decision ack=1'
    Assert-True (Test-Path -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilter.exe')) 'cancel kept app exe'
    Assert-True (Test-Path -LiteralPath $TestUninstallKey) 'cancel kept uninstall key'
    $after = Snapshot-Production
    Assert-True ($before -eq $after) 'production artifacts/keys/shortcuts unchanged after cancel'
    Add-Result 'cancel' 'PASS' 'nonzero exit, decision cancel/ack=1, install intact'
}

function Test-SecondInstance {
    Write-Log '--- second instance ---'
    Ensure-Installed
    Remove-Item -LiteralPath (Join-Path $TestInstallDir 'maintenance-decision.ini') -Force -ErrorAction SilentlyContinue
    $p1 = Start-TestSetup 'second-instance-first' -MaintenanceExtra '/auto:page=6'
    Assert-True (Wait-Diag $script:CurrentDiag 'auto maintenance waiting action=' 45) 'first setup waiting on maintenance page 6'
    $decision = Join-Path $TestInstallDir 'maintenance-decision.ini'
    $result = Join-Path $TestInstallDir 'uninstall-result.ini'
    # Keep action empty so the first setup keeps waiting instead of acknowledging;
    # this isolates the second-instance non-overwrite check from first-setup ack writes.
    Set-Content -LiteralPath $decision -Value "[maintenance]`nschema=1`naction=" -Encoding utf8
    Set-Content -LiteralPath $result -Value "[uninstall]`nschema=1`nstage=first`ndone=0" -Encoding utf8
    $decisionBefore = (Get-FileHash -LiteralPath $decision -Algorithm SHA256).Hash
    $resultBefore = (Get-FileHash -LiteralPath $result -Algorithm SHA256).Hash
    $windowsBefore = @(Get-InstallWindows).Count
    $env:FAF_DIAG_PATH = Join-Path $EvidenceDir 'second-instance-second.diag.log'
    $env:FAF_QA_MAINTENANCE_EXTRA = '/auto:page=6'
    $p2 = Start-Process -FilePath $SetupPath -PassThru
    $exited = $p2.WaitForExit(30000)
    if (-not $exited) { try { $p2.Kill($true) } catch {} }
    $windowsAfter = @(Get-InstallWindows).Count
    $decisionAfter = (Get-FileHash -LiteralPath $decision -Algorithm SHA256).Hash
    $resultAfter = (Get-FileHash -LiteralPath $result -Algorithm SHA256).Hash
    $h = Get-InstallWindow 0
    if ($h -ne [IntPtr]::Zero) { Close-InstallWindow $h $p1 } else { try { $p1.Kill($true) } catch {} }
    Assert-True $exited 'second setup exited while first was running'
    Write-Log "second instance exit code=$($p2.ExitCode)"
    Assert-True ($p2.ExitCode -ne 0) "second instance exits nonzero (actual $($p2.ExitCode))"
    Assert-True ($windowsBefore -eq 1) "exactly one GUI before second attempt (actual $windowsBefore)"
    Assert-True ($windowsAfter -eq 1) "exactly one GUI after second attempt (actual $windowsAfter)"
    Assert-True ($decisionAfter -eq $decisionBefore) 'second instance did not overwrite maintenance-decision.ini'
    Assert-True ($resultAfter -eq $resultBefore) 'second instance did not overwrite uninstall-result.ini'
    Assert-True (Test-Path -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilter.exe')) 'second instance did not damage install'
    Add-Result 'second-instance' 'PASS' "second exit=$($p2.ExitCode); one GUI; decision/result unchanged"
}

function Test-Uninstall([int]$DeleteUserData) {
    $tag = "uninstall-delete-$DeleteUserData"
    Write-Log "--- $tag ---"
    Remove-TestState
    Install-Fresh 'fresh'
    $before = Snapshot-Production

    New-Item -ItemType Directory -Force -Path $CanonicalDataDir, $CustomDataDir | Out-Null
    Set-Content -LiteralPath (Join-Path $CanonicalDataDir 'sentinel.txt') -Value 'canonical' -Encoding utf8
    Set-Content -LiteralPath (Join-Path $CustomDataDir 'sentinel.txt') -Value 'custom' -Encoding utf8
    $dataDir = Join-Path $TestInstallDir 'data'
    $internalDataDir = Join-Path $TestInstallDir '_internal\data'
    New-Item -ItemType Directory -Force -Path $dataDir, $internalDataDir | Out-Null
    Set-Content -LiteralPath (Join-Path $dataDir 'sentinel.txt') -Value 'install-data' -Encoding utf8
    Set-Content -LiteralPath (Join-Path $internalDataDir 'sentinel.txt') -Value 'install-internal-data' -Encoding utf8

    # Real installed app, with isolated data dir. The uninstall helper must close it.
    $env:FAF_DATA_DIR = $CustomDataDir
    $app = Start-Process -FilePath (Join-Path $TestInstallDir 'FreeAssetFilter.exe') -PassThru
    # Let the installed app finish first-run initialization before the helper tries to close it.
    Start-Sleep -Seconds 5
    Assert-True (-not $app.HasExited) "app running before $tag (pid=$($app.Id))"
    Assert-True ($app.Path.StartsWith($TestInstallDir, [StringComparison]::OrdinalIgnoreCase)) 'app image is the test install'
    Remove-Item Env:\FAF_DATA_DIR -ErrorAction SilentlyContinue

    $p = Start-TestUninstaller $tag $DeleteUserData
    $code = Complete-FinishPage $tag $p
    # Helper performs the actual deletions after the UI writes ui-done.
    $deadline = (Get-Date).AddSeconds(60)
    do {
        $helper = Get-Process -Name 'UninstallHelper' -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -and $_.Path.StartsWith($TestInstallDir, [StringComparison]::OrdinalIgnoreCase) }
        $resPath = Join-Path $TestInstallDir 'uninstall-result.ini'
        $tempUn = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -and $_.ExecutablePath -like "$env:TEMP\~nsu*" }
        if (-not $helper -and -not $tempUn -and (Test-Path -LiteralPath $resPath) -and (Read-IniValue $resPath 'uninstall' 'done') -eq '1') { break }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)
    Assert-True (-not $helper) 'uninstall helper exited'
    Assert-True ($code -eq 0) "$tag uninstaller exit code 0 (actual $code)"
    $appStill = Get-Process -Id $app.Id -ErrorAction SilentlyContinue
    Assert-True (-not $appStill) "uninstall helper closed the running app (pid=$($app.Id))"

    $result = Join-Path $TestInstallDir 'uninstall-result.ini'
    Assert-True (Test-Path -LiteralPath $result) 'uninstall-result.ini exists'
    Assert-True ((Read-IniValue $result 'uninstall' 'done') -eq '1') 'uninstall-result done=1'
    $stage = Read-IniValue $result 'uninstall' 'stage'
    Assert-True ($stage -in @('done','cancelled','failed')) "terminal stage (actual '$stage')"
    Start-Sleep -Milliseconds 700
    $warning = Read-IniValue $result 'uninstall' 'warning'
    Assert-True ($warning -eq 'install-dir-not-empty') "warning=install-dir-not-empty (actual '$warning')"
    Assert-True (-not (Test-Path -LiteralPath $TestUninstallKey)) 'test uninstall key removed'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilter.exe'))) 'app exe removed'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilterUninstall.exe'))) 'uninstaller exe removed'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $TestInstallDir 'libwinpthread-1.dll'))) 'libwinpthread removed'
    Assert-True (Test-Path -LiteralPath (Join-Path $TestInstallDir 'UninstallHelper.exe')) 'helper remains (install-dir-not-empty)'

    if ($DeleteUserData -eq 0) {
        Assert-True (Test-Path -LiteralPath (Join-Path $CanonicalDataDir 'sentinel.txt')) 'delete=0 kept canonical data'
        Assert-True (Test-Path -LiteralPath (Join-Path $dataDir 'sentinel.txt')) 'delete=0 kept install data dir'
        Assert-True (Test-Path -LiteralPath (Join-Path $internalDataDir 'sentinel.txt')) 'delete=0 kept _internal\data'
    } else {
        Assert-True (-not (Test-Path -LiteralPath $CanonicalDataDir)) 'delete=1 removed canonical data dir'
        Assert-True (-not (Test-Path -LiteralPath $dataDir)) 'delete=1 removed install data dir'
        Assert-True (-not (Test-Path -LiteralPath $internalDataDir)) 'delete=1 removed _internal\data'
    }
    Assert-True (Test-Path -LiteralPath (Join-Path $CustomDataDir 'sentinel.txt')) 'custom data always preserved'

    $after = Snapshot-Production
    Assert-True ($before -eq $after) "production artifacts/keys/shortcuts unchanged after $tag"
    Add-Result $tag 'PASS' 'warning=install-dir-not-empty; uninstall key/app removed; data semantics correct'
}

function Wait-HelperTerminal([string]$Tag, [int]$TimeoutSec = 90) {
    $resPath = Join-Path $TestInstallDir 'uninstall-result.ini'
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        $helper = Get-Process -Name 'UninstallHelper' -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -and $_.Path.StartsWith($TestInstallDir, [StringComparison]::OrdinalIgnoreCase) }
        $tempUn = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -and $_.ExecutablePath -like "$env:TEMP\~nsu*" }
        if (-not $helper -and -not $tempUn -and (Test-Path -LiteralPath $resPath) -and (Read-IniValue $resPath 'uninstall' 'done') -eq '1') { return }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)
    throw "$Tag helper did not reach done=1 within ${TimeoutSec}s"
}

function Test-FailureKillUi {
    Write-Log '--- failure kill UI ---'
    Remove-TestState
    Install-Fresh 'failure-kill-ui'
    $before = Snapshot-Production
    # Stop on the uninstall confirm page (6): a non-terminal page with a visible UI.
    $p = Start-TestUninstaller 'failure-kill-ui' 0 '/auto:mode=uninstall /auto:page=6'
    $hwnd = Wait-InstallWindow 0 45
    Save-WindowPng $hwnd (Join-Path $EvidenceDir 'failure-kill-ui-confirm.png')
    [uint32]$uiPid = 0
    [void][T20Native]::GetWindowThreadProcessId($hwnd, [ref]$uiPid)
    Assert-True ($uiPid -ne 0) "UI window has an owner pid (actual $uiPid)"
    $uiProc = Get-Process -Id $uiPid -ErrorAction SilentlyContinue
    Assert-True ($null -ne $uiProc) "UI process exists (pid=$uiPid)"
    Assert-True ($uiProc.Path -and $uiProc.Path.StartsWith($TestInstallDir, [StringComparison]::OrdinalIgnoreCase)) "killed process is the test UI (path=$($uiProc.Path))"
    Assert-True ($uiPid -ne $p.Id) 'UI pid differs from helper pid'
    Write-Log "killing only UI pid=$uiPid (helper pid=$($p.Id))"
    Stop-Process -Id $uiPid -Force
    Wait-HelperTerminal 'failure-kill-ui' 60
    if (-not $p.WaitForExit(30000)) { try { $p.Kill($true) } catch {} }
    $result = Join-Path $TestInstallDir 'uninstall-result.ini'
    Assert-True (Test-Path -LiteralPath $result) 'kill UI: uninstall-result.ini exists'
    Assert-True ((Read-IniValue $result 'uninstall' 'stage') -eq 'cancelled') "kill UI stage=cancelled (actual '$(Read-IniValue $result 'uninstall' 'stage')')"
    Assert-True ((Read-IniValue $result 'uninstall' 'done') -eq '1') 'kill UI done=1'
    Assert-True (Test-Path -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilter.exe')) 'kill UI kept app exe'
    Assert-True (Test-Path -LiteralPath $TestUninstallKey) 'kill UI kept uninstall key'
    $after = Snapshot-Production
    Assert-True ($before -eq $after) 'production untouched after UI kill'
    Add-Result 'failure-kill-ui' 'PASS' 'killed only the UI after its window appeared; stage=cancelled/done=1; nothing deleted'
}

function Test-FailureUiCopy {
    Write-Log '--- failure UI copy ---'
    Remove-TestState
    $before = Snapshot-Production
    $env:FAF_QA_FAIL_UI_COPY = '1'
    try {
        $p = Start-TestSetup 'failure-ui-copy' -InstallOpts '0000'
        $code = Complete-FinishPage 'failure-ui-copy' $p
    } finally {
        Remove-Item Env:\FAF_QA_FAIL_UI_COPY -ErrorAction SilentlyContinue
    }
    Assert-True ($code -ne 0) "UI copy failure setup exits nonzero (actual $code)"
    Assert-True (-not (Test-Path -LiteralPath $TestUninstallKey)) 'UI copy failure: no test uninstall key (and no UninstallString)'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilterUninstall.exe'))) 'UI copy failure: no uninstaller executable'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $TestInstallDir 'UninstallHelper.exe'))) 'UI copy failure: no helper written'
    $after = Snapshot-Production
    Assert-True ($before -eq $after) 'production untouched after UI copy failure'
    Add-Result 'failure-ui-copy' 'PASS' 'UI payload copy aborted before uninstaller/key; nonzero exit; production untouched'
}

function Test-FailureUiLaunch {
    Write-Log '--- failure UI launch ---'
    Remove-TestState
    Install-Fresh 'failure-ui-launch'
    $before = Snapshot-Production
    $ui = Join-Path $TestInstallDir 'FreeAssetFilterUninstall.exe'
    $app = Join-Path $TestInstallDir 'FreeAssetFilter.exe'
    $helper = Join-Path $TestInstallDir 'UninstallHelper.exe'
    $appHash = (Get-FileHash -LiteralPath $app -Algorithm SHA256).Hash
    $helperHash = (Get-FileHash -LiteralPath $helper -Algorithm SHA256).Hash
    Set-Content -LiteralPath $ui -Value 'not a portable executable' -Encoding ascii
    $diag = Join-Path $EvidenceDir 'failure-ui-launch.diag.log'
    Remove-Item -LiteralPath $diag -Force -ErrorAction SilentlyContinue
    $env:FAF_DIAG_PATH = $diag
    Remove-Item Env:\FAF_QA_UI_RUNTIME_EXTRA -ErrorAction SilentlyContinue
    try {
        # `_?=` keeps NSIS from self-copying to %TEMP%\~nsu*.tmp, so the outer stub
        # exits with the real uninstaller exit code instead of always returning 0.
        $p = Start-Process -FilePath $helper -ArgumentList @('/uninstall-launcher','/installdir',"$TestInstallDir",'/ui',"$ui","_?=$TestInstallDir") -PassThru
        if (-not $p.WaitForExit(60000)) { try { $p.Kill($true) } catch {}; throw 'UI launch failure: helper did not exit within 60s' }
        $helperExit = $p.ExitCode
        Write-Log "UI launch failure helper exit code=$helperExit"
        Assert-True ($helperExit -ne 0) "UI launch failure returns nonzero (actual $helperExit)"
        Wait-HelperTerminal 'failure-ui-launch' 60
    } finally {
        Remove-Item Env:\FAF_QA_UI_RUNTIME_EXTRA -ErrorAction SilentlyContinue
    }
    $result = Join-Path $TestInstallDir 'uninstall-result.ini'
    Assert-True (Test-Path -LiteralPath $result) 'UI launch failure: uninstall-result.ini exists'
    Assert-True ((Read-IniValue $result 'uninstall' 'stage') -eq 'cancelled') "UI launch failure stage=cancelled (actual '$(Read-IniValue $result 'uninstall' 'stage')')"
    Assert-True ((Read-IniValue $result 'uninstall' 'done') -eq '1') 'UI launch failure done=1'
    Assert-True ((Read-IniValue $result 'uninstall' 'warning') -eq 'ui-launch-failed') "UI launch failure warning=ui-launch-failed (actual '$(Read-IniValue $result 'uninstall' 'warning')')"
    Assert-True ((Get-FileHash -LiteralPath $app -Algorithm SHA256).Hash -eq $appHash) 'UI launch failure did not delete/modify app exe'
    Assert-True ((Get-FileHash -LiteralPath $helper -Algorithm SHA256).Hash -eq $helperHash) 'UI launch failure did not delete/modify helper'
    Assert-True ((Get-Content -LiteralPath $ui -Raw).Trim() -eq 'not a portable executable') 'UI launch failure did not delete the (faulty) UI file'
    Assert-True (Test-Path -LiteralPath $TestUninstallKey) 'UI launch failure kept uninstall key'
    $after = Snapshot-Production
    Assert-True ($before -eq $after) 'production untouched after UI launch failure'
    Add-Result 'failure-ui-launch' 'PASS' "helper_exit=$helperExit; cancelled/done=1/warning=ui-launch-failed; no files deleted"
}

function Test-ShortcutIsolation {
    Write-Log '--- shortcut isolation ---'
    Remove-TestState
    $before = Snapshot-Production
    # 1111 = desktop + startmenu + autostart + launch. Test mode must create only
    # FreeAssetFilterTest.lnk and must not touch production shortcuts.
    $p = Start-TestSetup 'shortcut-isolation-on' -InstallOpts '1111'
    $code = Complete-FinishPage 'shortcut-isolation-on' $p
    Assert-True ($code -eq 0) "shortcut isolation: 1111 setup exit 0 (actual $code)"
    Assert-True (Test-Path -LiteralPath $DesktopShortcut) 'options=1111: test desktop shortcut exists'
    Assert-True (Test-Path -LiteralPath $StartMenuShortcut) 'options=1111: flat test start-menu shortcut exists'
    $afterOn = Snapshot-Production
    Assert-True ($before -eq $afterOn) 'production shortcuts unchanged after test desktop=1/startmenu=1'

    # Force the next setup down the fresh-install path while keeping the test
    # shortcuts, so options=0000 must actively remove them.
    Remove-Item -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilter.exe') -Force
    Remove-Item -LiteralPath (Join-Path $TestInstallDir '_internal') -Recurse -Force
    $p2 = Start-TestSetup 'shortcut-isolation-off' -InstallOpts '0000'
    $code2 = Complete-FinishPage 'shortcut-isolation-off' $p2
    Assert-True ($code2 -eq 0) "shortcut isolation: 0000 setup exit 0 (actual $code2)"
    Assert-True (-not (Test-Path -LiteralPath $DesktopShortcut)) 'options=0000: test desktop shortcut removed'
    Assert-True (-not (Test-Path -LiteralPath $StartMenuShortcut)) 'options=0000: test start-menu shortcut removed'
    $afterOff = Snapshot-Production
    Assert-True ($before -eq $afterOff) 'production shortcuts unchanged after test desktop=0/startmenu=0'
    Add-Result 'shortcut-isolation' 'PASS' 'test shortcuts created/removed in isolation; production desktop/start-menu snapshots unchanged'
}

function Test-MaintenanceTempLifecycle {
    Write-Log '--- maintenance temp lifecycle (M1) ---'
    Remove-TestState
    $staleSuffix = [int]$PID
    while (Test-Path -LiteralPath (Join-Path $env:TEMP "FreeAssetFilterMaintenance-$staleSuffix")) {
        $staleSuffix += 100003
    }
    $stale = Join-Path $env:TEMP "FreeAssetFilterMaintenance-$staleSuffix"
    Register-MaintenanceTempPath $stale
    New-Item -ItemType Directory -Path $stale -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $stale 'stale-marker.txt') -Value 'stale-copy' -Encoding utf8
    (Get-Item -LiteralPath $stale).LastWriteTime = (Get-Date).AddHours(-25)
    Assert-True ((Get-Item -LiteralPath $stale).LastWriteTime -lt (Get-Date).AddHours(-24)) "stale temp dir is older than 24h: $stale"

    # A fresh setup must sweep the >24h copy before it creates its own copy.
    $p = Start-TestSetup 'maintenance-temp-sweep' -InstallOpts '0000'
    $code = Complete-FinishPage 'maintenance-temp-sweep' $p
    Assert-True ($code -eq 0) "temp sweep setup exit code 0 (actual $code)"
    Assert-True (-not (Test-Path -LiteralPath $stale)) 'setup removed the stale maintenance temp dir older than 24h'

    # A live maintenance UI must have its setup-owned copy (GUI + MinGW runtime).
    $p2 = Start-TestSetup 'maintenance-temp-active' -MaintenanceExtra '/auto:page=6'
    $hwnd = Wait-InstallWindow 0 45
    Save-WindowPng $hwnd (Join-Path $EvidenceDir 'maintenance-temp-active.png')
    $tempDir = Join-Path $env:TEMP "FreeAssetFilterMaintenance-$($p2.Id)"
    Register-MaintenanceTempPath $tempDir
    Assert-True (Test-Path -LiteralPath $tempDir) "active maintenance temp dir exists while UI is alive (pid=$($p2.Id))"
    Assert-True (Test-Path -LiteralPath (Join-Path $tempDir 'FreeAssetFilterInstaller.exe')) 'active temp dir contains FreeAssetFilterInstaller.exe'
    Assert-True (Test-Path -LiteralPath (Join-Path $tempDir 'libwinpthread-1.dll')) 'active temp dir contains libwinpthread-1.dll'
    Write-Log "captured active maintenance temp dir=$tempDir"

    # Normal UI exit: close the maintenance page and let the UI self-clean.
    [void][T20Native]::PostMessageW($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
    if (-not $p2.WaitForExit(90000)) {
        try { $p2.Kill($true) } catch {}
        throw 'maintenance temp lifecycle: setup did not exit after normal UI close'
    }
    Write-Log "maintenance temp setup exit code=$($p2.ExitCode)"
    $deadline = (Get-Date).AddSeconds(15)
    while ((Test-Path -LiteralPath $tempDir) -and ((Get-Date) -lt $deadline)) { Start-Sleep -Milliseconds 300 }
    Assert-True (-not (Test-Path -LiteralPath $tempDir)) 'normal UI exit removed its maintenance temp dir within 15s'
    Add-Result 'maintenance-temp-lifecycle' 'PASS' 'stale >24h swept; active copy had exe+dll; normal exit cleaned within 15s'
}

function Test-Failure {
    Write-Log '--- failure injections ---'
    # 1) UI missing -> helper silent uninstall succeeds.
    Remove-TestState
    Install-Fresh 'failure-ui-missing'
    Remove-Item -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilterUninstall.exe') -Force
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilterUninstall.exe'))) 'injected: UI missing'
    $env:FAF_DIAG_PATH = Join-Path $EvidenceDir 'failure-ui-missing.diag.log'
    Remove-Item Env:\FAF_QA_UI_RUNTIME_EXTRA -ErrorAction SilentlyContinue
    $p = Start-Process -FilePath (Join-Path $TestInstallDir 'UninstallHelper.exe') -ArgumentList @('/S','/installdir',"$TestInstallDir") -PassThru
    Assert-True ($p.WaitForExit(90000)) 'UI missing: helper silent uninstall exited'
    Assert-True ($p.ExitCode -eq 0) "UI missing: silent uninstall exit 0 (actual $($p.ExitCode))"
    $deadline = (Get-Date).AddSeconds(30)
    while ((Test-Path -LiteralPath $TestUninstallKey) -and ((Get-Date) -lt $deadline)) { Start-Sleep -Milliseconds 300 }
    Assert-True (-not (Test-Path -LiteralPath $TestUninstallKey)) 'UI missing: uninstall key removed'
    $deadline = (Get-Date).AddSeconds(30)
    while ((Test-Path -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilter.exe')) -and ((Get-Date) -lt $deadline)) { Start-Sleep -Milliseconds 300 }
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilter.exe'))) 'UI missing: app exe removed'
    Add-Result 'failure-ui-missing' 'PASS' 'silent uninstall exit 0; key/app removed'

    # 2) helper missing -> installed uninstall entry unavailable (observed, no deletion).
    Remove-TestState
    Install-Fresh 'failure-helper-missing'
    Remove-Item -LiteralPath (Join-Path $TestInstallDir 'UninstallHelper.exe') -Force
    $uninstallString = (Get-ItemProperty -LiteralPath $TestUninstallKey).UninstallString
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $TestInstallDir 'UninstallHelper.exe'))) 'injected: helper missing'
    Assert-True ($uninstallString -match 'UninstallHelper\.exe') 'UninstallString still points at missing helper'
    Assert-True (Test-Path -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilter.exe')) 'helper missing: app exe untouched'
    Assert-True (Test-Path -LiteralPath $TestUninstallKey) 'helper missing: uninstall key untouched'
    Add-Result 'failure-helper-missing' 'PASS' 'entry points at missing helper; state observed unchanged'

    # 3) UI cancel -> cancelled terminal, no deletion.
    Remove-TestState
    Install-Fresh 'failure-ui-cancel'
    $p = Start-TestUninstaller 'failure-ui-cancel' 0 '/auto:mode=uninstall /auto:action=cancel'
    Wait-HelperTerminal 'failure-ui-cancel'
    $hwnd = Get-InstallWindow 0
    if ($hwnd -ne [IntPtr]::Zero) {
        Save-WindowPng $hwnd (Join-Path $EvidenceDir 'failure-ui-cancel-terminal.png')
        [void][T20Native]::PostMessageW($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
    }
    if (-not $p.WaitForExit(30000)) { try { $p.Kill($true) } catch {} }
    $stage = Read-IniValue (Join-Path $TestInstallDir 'uninstall-result.ini') 'uninstall' 'stage'
    Assert-True ($stage -eq 'cancelled') "UI cancel stage=cancelled (actual '$stage')"
    Assert-True (Test-Path -LiteralPath (Join-Path $TestInstallDir 'FreeAssetFilter.exe')) 'UI cancel kept app exe'
    Assert-True (Test-Path -LiteralPath $TestUninstallKey) 'UI cancel kept uninstall key'
    Add-Result 'failure-ui-cancel' 'PASS' "exit=$($p.ExitCode); stage=cancelled; no deletion"

    Test-FailureKillUi
    Test-FailureUiCopy
    Test-FailureUiLaunch
    Test-MaintenanceTempLifecycle

    # Not reliably drivable in this elevated, healthy-disk session; explicit SKIPs.
    Add-Result 'failure-kill-helper' 'SKIP' 'requires deterministic helper kill window; not drivable reliably here'
    Add-Result 'failure-kill-setup-repair' 'SKIP' 'repair completes too fast to kill the waiting setup deterministically'
    Add-Result 'failure-readonly-nospace' 'SKIP' 'elevated session bypasses ACL; disk not near full'
}

function Invoke-ProductionGuard([scriptblock]$Body) {
    $before = Snapshot-Production
    & $Body
    $after = Snapshot-Production
    Assert-True ($before -eq $after) 'production snapshot unchanged'
}

function Invoke-Mode([string]$Name) {
    switch ($Name) {
        'fresh' { Install-Fresh }
        'repair' { Test-Repair }
        'cancel' { Test-Cancel }
        'second-instance' { Test-SecondInstance }
        'uninstall' { Test-Uninstall 0; Test-Uninstall 1 }
        'failure' { Test-Failure }
        'shortcut-isolation' { Test-ShortcutIsolation }
        'uac-cancel' { Add-Result 'uac-cancel' 'SKIP' 'elevated session; requires standard-user/manual UAC cancellation' }
        default { throw "unknown mode $Name" }
    }
}

$sw = [System.Diagnostics.Stopwatch]::StartNew()
Write-Log "T20 QA mode=$Mode setup=$SetupPath evidence=$EvidenceDir elevated=$([bool]([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))"
try {
    $modes = if ($Mode -eq 'all') { @('fresh', 'repair', 'cancel', 'second-instance', 'uninstall', 'failure', 'shortcut-isolation', 'uac-cancel') } else { @($Mode) }
    foreach ($m in $modes) { Invoke-Mode $m }
    Add-Result 'overall' 'PASS' "elapsed=$([math]::Round($sw.Elapsed.TotalSeconds,1))s"
    $exit = 0
} catch {
    Write-Log $_.Exception.ToString() 'ERROR'
    Add-Result 'overall' 'FAIL' $_.Exception.Message
    $exit = 1
} finally {
    if (-not $Keep) {
        try { Remove-TestState } catch { Write-Log "cleanup warning: $($_.Exception.Message)" 'WARN' }
    } else {
        Write-Log 'cleanup skipped (-Keep)'
    }
    Remove-Item Env:\FAF_DIAG_PATH, Env:\FAF_QA_INSTALL_OPTS, Env:\FAF_QA_MAINTENANCE_EXTRA, Env:\FAF_QA_UI_RUNTIME_EXTRA, Env:\FAF_QA_FAIL_UI_COPY -ErrorAction SilentlyContinue
    $summary = [pscustomobject]@{
        mode = $Mode
        setup = $SetupPath
        elapsed_seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1)
        results = $script:Results
    }
    $summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $SummaryPath -Encoding utf8
    Write-Log "summary: $SummaryPath"
}
exit $exit










