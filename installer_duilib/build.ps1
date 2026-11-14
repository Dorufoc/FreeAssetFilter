$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$build = Join-Path $root 'build'

# Tool resolution: an explicit environment override wins, then the usual local
# install location, then PATH. CI runners keep CMake/NSIS/MSYS2 elsewhere than this
# machine, so hardcoding a single path would make the workflow machine-specific.
function Resolve-Tool {
    param(
        [string]$Override,
        [string]$Preferred,
        [string]$CommandName,
        [string]$Label
    )
    if ($Override -and (Test-Path -LiteralPath $Override)) {
        return (Resolve-Path -LiteralPath $Override).ProviderPath
    }
    if ($Preferred -and (Test-Path -LiteralPath $Preferred)) { return $Preferred }
    $found = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    throw "Cannot locate ${Label}: '$Preferred' does not exist and '$CommandName' is not on PATH. Set the SPK_* override env var."
}

$cmake = Resolve-Tool -Override $env:SPK_CMAKE -Preferred 'C:\Program Files\CMake\bin\cmake.exe' -CommandName 'cmake' -Label 'CMake'
$nsis = Resolve-Tool -Override $env:SPK_NSIS -Preferred 'C:\Program Files (x86)\NSIS\makensis.exe' -CommandName 'makensis' -Label 'NSIS makensis'

$mingw = $env:SPK_MINGW_BIN
if (-not $mingw -or -not (Test-Path -LiteralPath (Join-Path $mingw 'g++.exe'))) {
    $mingw = 'C:\msys64\mingw64\bin'
}
if (-not (Test-Path -LiteralPath (Join-Path $mingw 'g++.exe'))) {
    # Last resort: derive the toolchain directory from g++ on PATH.
    $gxx = Get-Command 'g++.exe' -ErrorAction SilentlyContinue
    if (-not $gxx) { throw "Cannot locate MinGW g++ (checked SPK_MINGW_BIN, $mingw and PATH)." }
    $mingw = Split-Path -Parent $gxx.Source
}
$mingw = (Resolve-Path -LiteralPath $mingw).ProviderPath
$env:Path = "$mingw;$env:Path"
Write-Host "cmake : $cmake"
Write-Host "nsis  : $nsis"
Write-Host "mingw : $mingw"

# ---------------------------------------------------------------------------
# Version metadata comes from SPKVERSION (the single source of truth), so that a
# nightly build reports its own version in both the GUI EXE and the setup EXE
# instead of a frozen literal. Computed before CMake because the RC resource and
# the .nsi both consume it.
# ---------------------------------------------------------------------------
$versionFile = Join-Path $root '..\SPKVERSION'
if (-not (Test-Path -LiteralPath $versionFile)) { throw "Missing version file: $versionFile" }
$versionLines = @(Get-Content -LiteralPath $versionFile -Encoding UTF8)
if ($versionLines.Count -eq 0) { throw "Version file is empty: $versionFile" }
$versionLine = ([string]$versionLines[0]).Trim()
if (-not $versionLine) { throw "SPKVERSION first line (version) is empty: $versionFile" }
$displayVersion = $versionLine -replace '^[vV]', ''

# FILEVERSION/VIProductVersion require four dot-separated integers in 0..65535. A
# nightly build encodes its build day as days-since-2020-01-01 because YYYYMMDD would
# overflow the 16-bit field; a stable build keeps 0.
$numericMatch = [regex]::Match($displayVersion, '^(\d+)\.(\d+)\.(\d+)')
if (-not $numericMatch.Success) { throw "SPKVERSION has no x.y.z prefix: '$displayVersion'" }
$fieldMajor = [int]$numericMatch.Groups[1].Value
$fieldMinor = [int]$numericMatch.Groups[2].Value
$fieldPatch = [int]$numericMatch.Groups[3].Value
$fieldBuild = 0
$nightlyMatch = [regex]::Match($displayVersion, '\.nightly-(\d{8})$')
if ($nightlyMatch.Success) {
    $stamp = [datetime]::ParseExact($nightlyMatch.Groups[1].Value, 'yyyyMMdd', [System.Globalization.CultureInfo]::InvariantCulture)
    $fieldBuild = ($stamp.Date - [datetime]'2020-01-01').Days
}
foreach ($field in @(
        @{ Value = $fieldMajor; Name = 'major' },
        @{ Value = $fieldMinor; Name = 'minor' },
        @{ Value = $fieldPatch; Name = 'patch' },
        @{ Value = $fieldBuild; Name = 'build' })) {
    if ($field.Value -lt 0 -or $field.Value -gt 65535) {
        throw "Version field $($field.Name)=$($field.Value) is outside 0..65535"
    }
}
$numericVersion = "$fieldMajor.$fieldMinor.$fieldPatch.$fieldBuild"
Write-Host "Installer version: $displayVersion (numeric $numericVersion)"

# ---------------------------------------------------------------------------
# Compile the GUI.
# ---------------------------------------------------------------------------
if (Test-Path (Join-Path $build 'CMakeCache.txt')) { Remove-Item -LiteralPath $build -Recurse -Force }
New-Item -ItemType Directory -Force -Path $build | Out-Null
& $cmake -S $root -B $build -G 'MinGW Makefiles' `
    "-DCMAKE_CXX_COMPILER=$($mingw.Replace('\','/'))/g++.exe" `
    "-DCMAKE_RC_COMPILER=$($mingw.Replace('\','/'))/windres.exe" `
    "-DSPK_VERSION_MAJOR=$fieldMajor" `
    "-DSPK_VERSION_MINOR=$fieldMinor" `
    "-DSPK_VERSION_PATCH=$fieldPatch" `
    "-DSPK_VERSION_BUILD=$fieldBuild" `
    "-DSPK_VERSION_STRING=$displayVersion"
if ($LASTEXITCODE -ne 0) { throw 'CMake configure failed' }
& $cmake --build $build --config Release
if ($LASTEXITCODE -ne 0) { throw 'CMake build failed' }
$objdump = Join-Path $mingw 'objdump.exe'
$deps = (& $objdump -p (Join-Path $build 'SopeekInstaller.exe') | Select-String 'DLL Name') -join "`n"
if ($deps -match 'libgcc_s_seh-1|libstdc\+\+-6') { throw "Bootstrapper still depends on MSYS2 runtime:`n$deps" }
$installerOut = Join-Path $root '..\build\installer\SopeekInstaller.exe'
$runtimeDll = Join-Path $mingw 'libwinpthread-1.dll'
if (-not (Test-Path $runtimeDll)) { throw "Missing MinGW runtime: $runtimeDll" }
New-Item -ItemType Directory -Force -Path (Split-Path $installerOut) | Out-Null
Copy-Item (Join-Path $build 'SopeekInstaller.exe') $installerOut -Force
Copy-Item $runtimeDll (Join-Path (Split-Path $installerOut) 'libwinpthread-1.dll') -Force

# ---------------------------------------------------------------------------
# Package with NSIS.
# ---------------------------------------------------------------------------
# Payload size is measured HERE (before packaging) and handed to the GUI via NSIS.
# The GUI starts before the payload is extracted, so a runtime directory scan would
# report a partial sum; this compile-time value is the exact installed payload size.
$payloadDir = Join-Path $root '..\build\pyinstall\Sopeek'
if (-not (Test-Path -LiteralPath $payloadDir)) { throw "Missing payload: $payloadDir" }
$payloadBytes = (Get-ChildItem -LiteralPath $payloadDir -Recurse -File |
    Measure-Object -Property Length -Sum).Sum
if ($null -eq $payloadBytes) { $payloadBytes = 0 }
Write-Host "Payload bytes: $payloadBytes"

& $nsis `
    "/DPAYLOAD_BYTES=$payloadBytes" `
    "/DSPK_PRODUCT_VERSION=$displayVersion" `
    "/DSPK_PRODUCT_VERSION_NUMERIC=$numericVersion" `
    (Join-Path $root 'installer.nsi')
if ($LASTEXITCODE -ne 0) { throw 'NSIS build failed' }
Write-Host "Built: $installerOut"
