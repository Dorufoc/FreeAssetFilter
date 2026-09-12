<#
.SYNOPSIS
    Build FAF-Launcher.exe (W1 discrete-GPU launcher, todo 10).

.DESCRIPTION
    Compiles launcher/launcher.c (+ launcher.def) into
    launcher/FAF-Launcher.exe with MSVC (cl.exe). The resulting EXE
    exports NvOptimusEnablement=1 and
    AmdPowerXpressRequestHighPerformance=1 from its PE export table so
    the NVIDIA Optimus / AMD PowerXpress driver selects the discrete
    GPU for the process tree it spawns.

    The script locates MSVC via vswhere (VS 2022 BuildTools ok) and
    runs the compile inside a VsDevCmd-initialised cmd.exe so that
    INCLUDE/LIB are correct without importing a full Developer
    PowerShell session.

    MinGW fallback: if no MSVC is found but gcc exists, builds with
    gcc (-mwindows, --def launcher.def). Export verification then uses
    objdump instead of dumpbin.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File launcher/build_launcher.ps1
#>
[CmdletBinding()]
param(
    [ValidateSet('Auto', 'MSVC', 'MinGW')]
    [string]$Toolchain = 'Auto',

    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Src = Join-Path $PSScriptRoot 'launcher.c'
$Def = Join-Path $PSScriptRoot 'launcher.def'
$Out = Join-Path $PSScriptRoot 'FAF-Launcher.exe'

if ($Clean -and (Test-Path $Out)) {
    Remove-Item -LiteralPath $Out -Force
    Write-Host "[launcher] removed $Out"
}

foreach ($f in @($Src, $Def)) {
    if (-not (Test-Path -LiteralPath $f)) { throw "missing source file: $f" }
}

function Find-MsvcInstall {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} `
        'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) { return $null }
    $path = & $vswhere -latest -products * -property installationPath `
        2>$null | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($path)) { return $null }
    return $path.Trim()
}

function Build-Msvc([string]$installPath) {
    $devCmd = Join-Path $installPath 'Common7\Tools\VsDevCmd.bat'
    if (-not (Test-Path -LiteralPath $devCmd)) {
        throw "VsDevCmd.bat not found under $installPath"
    }
    # cl resolves launcher.c relative to the repo root; the .def file
    # travels as an extra input so its EXPORTS section is honoured.
    # NOTE: cmd.exe quoting — the whole inner command is one /c string.
    $inner = "call `"$devCmd`" -arch=amd64 -no_logo >nul 2>&1 && " +
        "cl.exe /nologo /O2 /W3 /DUNICODE /D_UNICODE " +
        "`"$Src`" `"$Def`" " +
        "/Fe:`"$Out`" /link /SUBSYSTEM:WINDOWS user32.lib shell32.lib"
    Write-Host "[launcher] MSVC: $installPath"
    Write-Host "[launcher] $inner"
    $null = & cmd.exe /c $inner
    if ($LASTEXITCODE -ne 0) { throw "cl.exe failed (exit $LASTEXITCODE)" }
}

function Build-MinGW {
    $gcc = Get-Command gcc -ErrorAction SilentlyContinue
    if ($null -eq $gcc) { throw 'no gcc on PATH for MinGW fallback' }
    $objdump = Get-Command objdump -ErrorAction SilentlyContinue
    Write-Host "[launcher] MinGW: $($gcc.Source)"
    & gcc -O2 -Wall -mwindows "-Wl,--def=$Def" -o $Out $Src
    if ($LASTEXITCODE -ne 0) { throw "gcc failed (exit $LASTEXITCODE)" }
    if ($null -ne $objdump) {
        Write-Host '[launcher] objdump export table:'
        & objdump -p $Out | Select-String -Pattern `
            'NvOptimusEnablement|AmdPowerXpressRequestHighPerformance'
    }
}

$msvc = Find-MsvcInstall
if (($Toolchain -eq 'MSVC') -or (($Toolchain -eq 'Auto') -and ($null -ne $msvc))) {
    if ($null -eq $msvc) { throw 'MSVC requested but no VS installation found' }
    Build-Msvc $msvc
}
elseif (($Toolchain -eq 'MinGW') -or ($Toolchain -eq 'Auto')) {
    Build-MinGW
}
else {
    throw 'no C toolchain found (need MSVC via vswhere, or gcc on PATH)'
}

if (-not (Test-Path -LiteralPath $Out)) { throw "build produced no $Out" }
$size = (Get-Item -LiteralPath $Out).Length
Write-Host "[launcher] built $Out ($size bytes)"

# Export-table verification (MSVC path): fail closed when a name is missing.
$dumpbin = Get-Command dumpbin -ErrorAction SilentlyContinue
if ($null -ne $dumpbin) {
    $exports = & dumpbin /exports $Out 2>&1 | Out-String
    Write-Host $exports
    foreach ($sym in @('NvOptimusEnablement',
            'AmdPowerXpressRequestHighPerformance')) {
        if ($exports -notmatch [regex]::Escape($sym)) {
            throw "export verification FAILED: $sym not in export table"
        }
    }
    Write-Host '[launcher] export verification PASSED (both symbols present)'
}
else {
    Write-Host '[launcher] dumpbin not on PATH — verify manually:'
    Write-Host "    dumpbin /exports `"$Out`""
}
