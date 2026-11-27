$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$build = Join-Path $root 'build'
# 本脚本位于 packaging/installer/，仓库根在上两级（重构前在 installer_duilib/，只上一级）。
# 后续所有跨目录路径都以 $repoRoot 为基准，避免每处再各自数层级。
$repoRoot = Split-Path -Parent (Split-Path -Parent $root)

# CMake writes the source path as UTF-8 bytes while mingw32-make interprets them
# with the active ANSI code page. A non-ASCII repository path therefore fails
# halfway through the build, often without a visible error when launched by
# double-click. Fail fast here and point users at the supported entry point.
if ($repoRoot -match '[^\x00-\x7F]') {
    throw @"
检测到仓库路径包含非 ASCII 字符（中文），CMake + MinGW 无法可靠构建：
  $repoRoot

请改为双击仓库根目录的 build.cmd。它会提示中文路径不受支持，并自动切换到
纯英文临时目录继续完成打包。
"@
}

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
$versionFile = Join-Path $repoRoot 'SPKVERSION'
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
# Package naming: <app>-<version>-<platform>-<arch>-<timestamp>.exe
# 例如 Sopeek-2.0.0-windows-x64-261118153045.exe、
#      Sopeek-2.0.0.nightly-20261114-windows-x64-261118153045.exe
#
# 时间戳是本地时间的 yyMMddHHmmss（年只取后两位），让每次构建产出唯一文件名：
# 同名产物不会被静默覆盖，下载或比对不同构建时也不会混淆。格式化显式使用
# InvariantCulture，避免非公历文化（如佛历）把年份算偏。
#
# 平台/架构描述的是「这个包适配的系统」而不是 NSIS 存根自身的位数：NSIS 3 存根固定
# 是 32 位，但 payload 安装到 $PROGRAMFILES64，因此包面向 64 位 Windows。将来若出
# arm64 版本，用环境变量覆盖即可，无需改文件名逻辑。
#
# 注意：native/spk_updater 按 `Sopeek-<版本>-windows-<架构>[-<时间戳>].exe` 解析
# 发布资产（见 native/spk_updater/src/release.rs），改这里的命名格式时必须同步更新。
# ---------------------------------------------------------------------------
$targetPlatform = if ($env:SPK_TARGET_PLATFORM) { $env:SPK_TARGET_PLATFORM.Trim() } else { 'windows' }
$targetArch = if ($env:SPK_TARGET_ARCH) { $env:SPK_TARGET_ARCH.Trim() } else { 'x64' }
$buildStamp = (Get-Date).ToString('yyMMddHHmmss', [System.Globalization.CultureInfo]::InvariantCulture)
$setupFileName = "Sopeek-$displayVersion-$targetPlatform-$targetArch-$buildStamp.exe"
# 相对 installer.nsi 所在目录（packaging/installer/），避免把含空格的绝对路径塞进
# makensis 的 -D 参数；installer.nsi 自身也按「上两级 = 仓库根」解析（见该文件的
# Icon / PAYLOAD / File 指令）。
$setupOutRel = "..\..\build\$setupFileName"
$setupOutAbs = Join-Path $repoRoot "build\$setupFileName"
Write-Host "Setup package: $setupFileName"

# ---------------------------------------------------------------------------
# Payload preflight MUST run before compiling the GUI. Otherwise a standalone
# installer build produces a plausible-looking SopeekInstaller.exe and only
# then fails with "Missing payload", which users easily mistake for the final
# installer.
# ---------------------------------------------------------------------------
$payloadDir = Join-Path $repoRoot 'build\pyinstall\Sopeek'
$payloadExe = Join-Path $payloadDir 'Sopeek.exe'
$payloadInternal = Join-Path $payloadDir '_internal'
if (-not (Test-Path -LiteralPath $payloadExe)) {
    throw "Missing payload executable: $payloadExe. Run python packaging/build.py first."
}
if (-not (Test-Path -LiteralPath $payloadInternal)) {
    throw "Missing payload _internal directory: $payloadInternal. Run python packaging/build.py first."
}

# ---------------------------------------------------------------------------
# Native Explorer integration. The shell extension DLL ships inside the payload:
# install_engine copies the payload tree verbatim, and Section Install registers
# "$INSTDIR\SopeekShellExt.dll" as the IExplorerCommand server behind the
# 「用Sopeek软件打开」/「使用Sopeek打开」 verbs. Building it here keeps the
# packaged DLL, the CLSIDs in installer.nsi and the app version in lockstep.
# Built before payloadBytes is measured so the size forwarded to NSIS is exact.
# ---------------------------------------------------------------------------
$shellExtScript = Join-Path $repoRoot 'packaging\shell_ext\build.ps1'
if (-not (Test-Path -LiteralPath $shellExtScript)) {
    throw "Missing shell extension build script: $shellExtScript"
}
$shellExtBuild = Join-Path $repoRoot 'build\shell_ext'
$shellExtDll = Join-Path $shellExtBuild 'SopeekShellExt.dll'
& $shellExtScript -CMake $cmake -MinGWBin $mingw -Destination $payloadDir -BuildDir $shellExtBuild
if (-not (Test-Path -LiteralPath $shellExtDll)) {
    throw "Shell extension build produced no DLL: $shellExtDll"
}
Write-Host "Shell extension: $shellExtDll"

# ---------------------------------------------------------------------------
# Windows 11 modern context menu. The top-level menu only lists commands declared
# by an application with package identity, so the payload also carries a signed
# sparse package (SopeekShellMenu.msix + .cer + register/unregister scripts).
# Section Install registers it for the installing user during production install;
# uninstall Stage 3 removes it. Both the classic verbs and the package point at the
# same CLSIDs and the same "$INSTDIR\SopeekShellExt.dll".
# ---------------------------------------------------------------------------
$shellMenuScript = Join-Path $repoRoot 'packaging\shell_menu\build.ps1'
if (-not (Test-Path -LiteralPath $shellMenuScript)) {
    throw "Missing shell menu package build script: $shellMenuScript"
}
& $shellMenuScript -OutputDirectory $payloadDir
foreach ($artifact in @('SopeekShellMenu.msix', 'SopeekShellMenu.cer', 'shell_menu_register.ps1', 'resources.pri')) {
    $path = Join-Path $payloadDir $artifact
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Shell menu build produced no $artifact in $payloadDir"
    }
}
Write-Host "Shell menu package: $(Join-Path $payloadDir 'SopeekShellMenu.msix')"

# Sparse package logos are resolved from the external location at run time (not from
# the msix). Without Assets\ next to Sopeek.exe the taskbar shows a blank placeholder
# for windows started through the packaged command, so ship the logo set with the app.
$shellMenuAssets = Join-Path $repoRoot 'packaging\shell_menu\Assets'
if (-not (Test-Path -LiteralPath $shellMenuAssets)) {
    throw "Missing sparse package assets: $shellMenuAssets"
}
$payloadAssets = Join-Path $payloadDir 'Assets'
if (Test-Path -LiteralPath $payloadAssets) { Remove-Item -LiteralPath $payloadAssets -Recurse -Force }
Copy-Item -LiteralPath $shellMenuAssets -Destination $payloadAssets -Recurse -Force
Write-Host "Sparse package assets: $payloadAssets"

$payloadBytes = (Get-ChildItem -LiteralPath $payloadDir -Recurse -File |
    Measure-Object -Property Length -Sum).Sum
if ($null -eq $payloadBytes) { $payloadBytes = 0 }
if ($payloadBytes -le 0) {
    throw "Payload directory is empty: $payloadDir"
}
Write-Host "Payload: $payloadDir ($payloadBytes bytes)"

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
$guiOut = Join-Path $build 'SopeekInstaller.exe'
if (-not (Test-Path -LiteralPath $guiOut)) { throw "CMake did not produce the installer GUI: $guiOut" }
$objdump = Join-Path $mingw 'objdump.exe'
$deps = (& $objdump -p $guiOut | Select-String 'DLL Name') -join "`n"
if ($deps -match 'libgcc_s_seh-1|libstdc\+\+-6') { throw "Bootstrapper still depends on MSYS2 runtime:`n$deps" }
$installerOut = Join-Path $repoRoot 'build\installer\SopeekInstaller.exe'
$runtimeDll = Join-Path $mingw 'libwinpthread-1.dll'
if (-not (Test-Path $runtimeDll)) { throw "Missing MinGW runtime: $runtimeDll" }
New-Item -ItemType Directory -Force -Path (Split-Path $installerOut) | Out-Null
Copy-Item -LiteralPath $guiOut -Destination $installerOut -Force
Copy-Item -LiteralPath $runtimeDll `
    -Destination (Join-Path (Split-Path $installerOut) 'libwinpthread-1.dll') -Force

# ---------------------------------------------------------------------------
# Package with NSIS.
# ---------------------------------------------------------------------------
# Payload size was measured before compiling the GUI and is forwarded to the
# bootstrapper via NSIS. The GUI starts before extraction, so a runtime scan
# would only see a partial sum.
Write-Host "Payload bytes: $payloadBytes"

# Remove the expected output first: if makensis fails silently, a stale package
# from a previous build must not be mistaken for this run's artifact.
if (Test-Path -LiteralPath $setupOutAbs) {
    Remove-Item -LiteralPath $setupOutAbs -Force
}

& $nsis `
    "/DPAYLOAD_BYTES=$payloadBytes" `
    "/DSPK_PRODUCT_VERSION=$displayVersion" `
    "/DSPK_PRODUCT_VERSION_NUMERIC=$numericVersion" `
    "/DSPK_OUTFILE=$setupOutRel" `
    (Join-Path $root 'installer.nsi')
if ($LASTEXITCODE -ne 0) { throw 'NSIS build failed' }
if (-not (Test-Path -LiteralPath $setupOutAbs)) { throw "NSIS did not produce the expected package: $setupOutAbs" }
$setupItem = Get-Item -LiteralPath $setupOutAbs
if ($setupItem.Length -le 0) { throw "NSIS produced an empty package: $setupOutAbs" }
Write-Host "Built GUI   : $installerOut"
Write-Host "Built setup : $setupOutAbs"
