$ErrorActionPreference = 'Stop'
# T18: build an isolated SPK_TESTMODE NSIS test setup.
#
# This script is build-only. It never runs the produced setup/uninstaller and
# never writes HKCU/HKLM or %LOCALAPPDATA% install/data directories.
#
# Pipeline:
#   1. snapshot the three production artifacts (hash + size + mtime);
#   2. statically audit the installer.nsi SPK_TESTMODE / production branches;
#   3. rebuild the SPK_TESTMODE GUI via tools\build_test_gui.ps1;
#   4. compile installer.nsi with /DSPK_TESTMODE and an explicit test OutFile;
#   5. re-check production artifacts and objdump the test GUI.
#
# Output: <repo>\build\test-installer\Sopeek_NSIS_Test.exe

$toolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$installerDir = Split-Path -Parent $toolsDir
$repoRoot = Split-Path -Parent $installerDir
$buildDir = Join-Path $repoRoot 'build'
$testDir = Join-Path $buildDir 'test-installer'
$nsiPath = Join-Path $installerDir 'installer.nsi'
$buildTestGui = Join-Path $toolsDir 'build_test_gui.ps1'
$nsisExe = 'C:\Program Files (x86)\NSIS\makensis.exe'
$objdumpExe = 'C:\msys64\mingw64\bin\objdump.exe'
$mingwDll = 'C:\msys64\mingw64\bin\libwinpthread-1.dll'
$testGui = Join-Path $testDir 'SopeekInstaller.exe'
$testDll = Join-Path $testDir 'libwinpthread-1.dll'
$testGuiBuild = Join-Path $installerDir 'build\test-gui\SopeekInstaller.exe'
$testSetup = Join-Path $testDir 'Sopeek_NSIS_Test.exe'
$productionSetup = Join-Path $buildDir 'Sopeek_NSIS_Setup.exe'
$productionGui = Join-Path $buildDir 'installer\SopeekInstaller.exe'
$productionDll = Join-Path $buildDir 'installer\libwinpthread-1.dll'
$productionPaths = @($productionGui, $productionDll, $productionSetup)

function Get-ArtifactSnapshot {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        # Clean checkout / T22 sequence: production artifacts may not exist yet.
        # The missing state is itself part of the snapshot and must remain absent.
        return $null
    }
    $item = Get-Item -LiteralPath $Path
    return [pscustomobject]@{
        Path             = $item.FullName
        Length           = $item.Length
        LastWriteTimeUtc = $item.LastWriteTimeUtc
        SHA256           = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    }
}

function Get-ProductionSnapshots {
    param([Parameter(Mandatory)][string[]]$Paths)

    # Use an explicit indexed array so a $null snapshot keeps its slot; piping
    # through ForEach-Object would silently drop missing artifacts.
    $snapshots = [object[]]::new($Paths.Count)
    for ($i = 0; $i -lt $Paths.Count; $i++) {
        $snapshots[$i] = Get-ArtifactSnapshot -Path $Paths[$i]
    }
    return ,$snapshots
}

function Assert-ProductionUnchanged {
    param(
        [Parameter(Mandatory)][string[]]$Paths,
        [object[]]$Before,
        [object[]]$After,
        [Parameter(Mandatory)][string]$Stage
    )

    if ($null -eq $Before -or $null -eq $After) {
        throw "Internal error: missing production snapshot array at stage ${Stage}"
    }
    if ($Before.Count -ne $Paths.Count -or $After.Count -ne $Paths.Count) {
        throw "Internal error: production snapshot count mismatch at stage ${Stage}"
    }

    $problems = [System.Collections.Generic.List[string]]::new()
    for ($i = 0; $i -lt $Paths.Count; $i++) {
        $path = $Paths[$i]
        $old = $Before[$i]
        $new = $After[$i]

        if ($null -eq $old -and $null -eq $new) {
            continue
        }
        if ($null -eq $old -and $null -ne $new) {
            $problems.Add("test build created a production artifact: $path")
            continue
        }
        if ($null -ne $old -and $null -eq $new) {
            $problems.Add("test build removed a production artifact: $path")
            continue
        }
        if ($new.SHA256 -ne $old.SHA256) {
            $problems.Add("SHA256 changed after ${Stage}: $path [$($old.SHA256) -> $($new.SHA256)]")
        }
        if ($new.Length -ne $old.Length) {
            $problems.Add("size changed after ${Stage}: $path [$($old.Length) -> $($new.Length)]")
        }
        if ($new.LastWriteTimeUtc -ne $old.LastWriteTimeUtc) {
            $problems.Add("mtime changed after ${Stage}: $path [$($old.LastWriteTimeUtc.ToString('o')) -> $($new.LastWriteTimeUtc.ToString('o'))]")
        }
    }
    if ($problems.Count -gt 0) {
        throw "Production artifacts changed during test build:`n - $($problems -join "`n - ")"
    }
}

# Parse installer.nsi compile-time branches under the assumption SPK_TESTMODE is
# defined. Only SPK_TESTMODE conditionals affect the active-state calculation;
# other !ifdef/!ifndef/!if directives are tracked solely for nesting balance.
function Get-NsisTestModeLines {
    param([string[]]$Lines)

    $records = [System.Collections.Generic.List[object]]::new()
    $stack = [System.Collections.Generic.Stack[object]]::new()
    $active = $true

    for ($i = 0; $i -lt $Lines.Count; $i++) {
        $trim = $Lines[$i].Trim()
        $lineNo = $i + 1
        $isElse = $false

        if ($trim -match '^!ifdef\s+SPK_TESTMODE\b') {
            $stack.Push([pscustomobject]@{ IsTest = $true; ParentActive = $active; DefinedWhenTrue = $true })
            # SPK_TESTMODE is defined for this build, so the if-branch is active.
        }
        elseif ($trim -match '^!ifndef\s+SPK_TESTMODE\b') {
            $stack.Push([pscustomobject]@{ IsTest = $true; ParentActive = $active; DefinedWhenTrue = $false })
            # SPK_TESTMODE is defined, so the ifndef-branch is inactive.
            $active = $false
        }
        elseif ($trim -match '^!(?:ifdef|ifndef|if|ifmacrodef|ifmacrondef)\b') {
            $stack.Push([pscustomobject]@{ IsTest = $false; ParentActive = $active; DefinedWhenTrue = $true })
        }
        elseif ($trim -match '^!else\b') {
            if ($stack.Count -eq 0) { throw "Unbalanced !else at installer.nsi:$lineNo" }
            $top = $stack.Peek()
            if ($top.IsTest) {
                $isElse = $true
                if ($top.DefinedWhenTrue) {
                    # !ifdef SPK_TESTMODE / !else => inactive because the macro is defined.
                    $active = $false
                }
                else {
                    # !ifndef SPK_TESTMODE / !else => active when the macro is defined.
                    $active = $top.ParentActive
                }
            }
        }
        elseif ($trim -match '^!endif\b') {
            if ($stack.Count -eq 0) { throw "Unbalanced !endif at installer.nsi:$lineNo" }
            $top = $stack.Pop()
            $active = $top.ParentActive
        }

        $records.Add([pscustomobject]@{
            LineNumber  = $lineNo
            Text        = $Lines[$i]
            ActiveInTest = $active
            IsTestElse  = $isElse
        })
    }

    if ($stack.Count -ne 0) { throw 'Unbalanced NSIS conditional directives in installer.nsi' }
    return $records.ToArray()
}

function Assert-ActiveTestLine {
    param(
        [Parameter(Mandatory)][object[]]$Records,
        [Parameter(Mandatory)][string]$Exact,
        [Parameter(Mandatory)][string]$Label
    )

    $found = @($Records | Where-Object {
        $_.ActiveInTest -and $_.Text.Trim() -eq $Exact
    })
    if ($found.Count -eq 0) {
        throw "NSIS test-isolation assertion failed ($Label): no active SPK_TESTMODE line equals: $Exact"
    }
    return $found[0]
}

Write-Host "T18 test installer build"
Write-Host "  repo root : $repoRoot"
Write-Host "  test output: $testSetup"

foreach ($required in @($nsiPath, $buildTestGui, $nsisExe, $objdumpExe, $mingwDll)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Missing required file: $required"
    }
}
if ([string]::Equals($testSetup, $productionSetup, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to build: test setup path equals the production setup path"
}
if (-not $testSetup.StartsWith($testDir, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to build: test setup is outside $testDir"
}

# ---------------------------------------------------------------------------
# Production snapshot (must be taken before any build command runs).
# ---------------------------------------------------------------------------
$productionBefore = Get-ProductionSnapshots -Paths $productionPaths
Write-Host 'Production snapshot before build:'
for ($i = 0; $i -lt $productionPaths.Count; $i++) {
    $snapshot = $productionBefore[$i]
    if ($null -eq $snapshot) {
        Write-Host ("  {0}`n    ABSENT (clean checkout; test build must not create it)" -f $productionPaths[$i])
    }
    else {
        Write-Host ("  {0}`n    SHA256 {1}  size {2}  mtime {3:o}" -f $snapshot.Path, $snapshot.SHA256, $snapshot.Length, $snapshot.LastWriteTimeUtc)
    }
}

# ---------------------------------------------------------------------------
# Static NSIS branch assertions (fail before the expensive build if violated).
# ---------------------------------------------------------------------------
$nsiLines = Get-Content -LiteralPath $nsiPath
$nsiRecords = @(Get-NsisTestModeLines -Lines $nsiLines)

Assert-ActiveTestLine -Records $nsiRecords -Label 'test InstallDir' `
    -Exact 'InstallDir "$LOCALAPPDATA\SopeekTest"' | Out-Null
Assert-ActiveTestLine -Records $nsiRecords -Label 'test InstallDirRegKey' `
    -Exact 'InstallDirRegKey HKCU "Software\SopeekTest" "InstallDir"' | Out-Null
Assert-ActiveTestLine -Records $nsiRecords -Label 'test GUI File source' `
    -Exact 'File "..\build\test-installer\SopeekInstaller.exe"' | Out-Null
Assert-ActiveTestLine -Records $nsiRecords -Label 'test runtime File source' `
    -Exact 'File "..\build\test-installer\libwinpthread-1.dll"' | Out-Null

$badTestFileRefs = @($nsiRecords | Where-Object {
    $_.ActiveInTest -and -not $_.Text.Trim().StartsWith(';') -and $_.Text -match 'build\\installer\\'
})
if ($badTestFileRefs.Count -gt 0) {
    $detail = ($badTestFileRefs | ForEach-Object { "installer.nsi:$($_.LineNumber): $($_.Text.Trim())" }) -join "`n"
    throw "NSIS test-isolation assertion failed: SPK_TESTMODE branch references production build/installer:`n$detail"
}

$activeRegistryLines = @($nsiRecords | Where-Object {
    $_.ActiveInTest -and -not $_.Text.Trim().StartsWith(';') -and
        $_.Text -match '\b(?:WriteRegStr|WriteRegDWORD|DeleteRegKey|DeleteRegValue|ReadRegStr)\b'
})
if ($activeRegistryLines.Count -eq 0) {
    throw 'NSIS test-isolation assertion failed: no active test-mode registry operations found'
}
$badHklm = @($activeRegistryLines | Where-Object { $_.Text -match '\bHKLM\b' })
if ($badHklm.Count -gt 0) {
    throw "NSIS test-isolation assertion failed: test mode writes/reads HKLM:`n$(($badHklm | ForEach-Object { $_.Text.Trim() }) -join "`n")"
}
$badProductionKeys = @($activeRegistryLines | Where-Object { $_.Text -match 'Software\\Sopeek(?!Test)' })
if ($badProductionKeys.Count -gt 0) {
    throw "NSIS test-isolation assertion failed: test mode touches a production key:`n$(($badProductionKeys | ForEach-Object { $_.Text.Trim() }) -join "`n")"
}

$testWriteRegStr = @($activeRegistryLines | Where-Object { $_.Text -match '\bWriteRegStr\b' })
if ($testWriteRegStr.Count -eq 0) {
    throw 'NSIS test-isolation assertion failed: test mode has no WriteRegStr'
}
$badWriteRegStr = @($testWriteRegStr | Where-Object { $_.Text -notmatch 'SopeekTest' })
if ($badWriteRegStr.Count -gt 0) {
    throw "NSIS test-isolation assertion failed: test-mode WriteRegStr is not under SopeekTest:`n$(($badWriteRegStr | ForEach-Object { $_.Text.Trim() }) -join "`n")"
}

$testDeleteRegKey = @($activeRegistryLines | Where-Object { $_.Text -match '\bDeleteRegKey\b' })
if ($testDeleteRegKey.Count -eq 0) {
    throw 'NSIS test-isolation assertion failed: test mode has no DeleteRegKey'
}
$badDeleteRegKey = @($testDeleteRegKey | Where-Object { $_.Text -notmatch 'SopeekTest' })
if ($badDeleteRegKey.Count -gt 0) {
    throw "NSIS test-isolation assertion failed: test-mode DeleteRegKey is not under SopeekTest:`n$(($badDeleteRegKey | ForEach-Object { $_.Text.Trim() }) -join "`n")"
}

$testDeleteRegValue = @($activeRegistryLines | Where-Object { $_.Text -match '\bDeleteRegValue\b' })
if ($testDeleteRegValue.Count -gt 0) {
    throw "NSIS test-isolation assertion failed: test mode contains DeleteRegValue:`n$(($testDeleteRegValue | ForEach-Object { $_.Text.Trim() }) -join "`n")"
}
$testRunRefs = @($nsiRecords | Where-Object {
    $_.ActiveInTest -and -not $_.Text.Trim().StartsWith(';') -and $_.Text -match 'CurrentVersion\\Run'
})
if ($testRunRefs.Count -gt 0) {
    throw "NSIS test-isolation assertion failed: test mode touches the production Run key:`n$(($testRunRefs | ForEach-Object { "installer.nsi:$($_.LineNumber): $($_.Text.Trim())" }) -join "`n")"
}

$testUninstallString = @($nsiRecords | Where-Object {
    $_.ActiveInTest -and $_.Text.Trim() -match '^WriteRegStr\b' -and $_.Text -match '"UninstallString"'
})
if ($testUninstallString.Count -ne 1) {
    throw "NSIS test-isolation assertion failed: expected one active test-mode UninstallString, found $($testUninstallString.Count)"
}
$uninstallStringText = $testUninstallString[0].Text
if ($uninstallStringText -notmatch [regex]::Escape('$INSTDIR\UninstallHelper.exe')) {
    throw "NSIS test-isolation assertion failed: test UninstallString does not point at `$INSTDIR\UninstallHelper.exe"
}
if ($uninstallStringText -notmatch [regex]::Escape('$INSTDIR\SopeekUninstall.exe')) {
    throw "NSIS test-isolation assertion failed: test UninstallString does not point at `$INSTDIR\SopeekUninstall.exe"
}

# D13/F2: the test branch must use the SopeekTest stem and must never
# reference a production shortcut path (desktop singleton, Start Menu folder, or
# the legacy flat production Start Menu file). This catches a regression to the
# pre-F2 hard-coded Sopeek.lnk before packaging.
Assert-ActiveTestLine -Records $nsiRecords -Label 'test shortcut stem define' `
    -Exact '!define SHORTCUT_STEM_TEST "SopeekTest"' | Out-Null
Assert-ActiveTestLine -Records $nsiRecords -Label 'selected test shortcut stem' `
    -Exact '!define SHORTCUT_STEM "${SHORTCUT_STEM_TEST}"' | Out-Null
Assert-ActiveTestLine -Records $nsiRecords -Label 'test desktop shortcut create' `
    -Exact 'CreateShortcut "$DESKTOP\${SHORTCUT_STEM}.lnk" "$INSTDIR\Sopeek.exe"' | Out-Null
Assert-ActiveTestLine -Records $nsiRecords -Label 'test start-menu shortcut create' `
    -Exact 'CreateShortcut "$SMPROGRAMS\${SHORTCUT_STEM}.lnk" "$INSTDIR\Sopeek.exe"' | Out-Null

$testShortcutOps = @($nsiRecords | Where-Object {
    $_.ActiveInTest -and -not $_.Text.Trim().StartsWith(';') -and
        $_.Text -match '\$\{SHORTCUT_STEM\}' -and $_.Text -match '\b(?:CreateShortcut|Delete|RMDir)\b'
})
if ($testShortcutOps.Count -lt 6) {
    throw "NSIS test-isolation assertion failed: expected at least 6 active test-mode shortcut operations, found $($testShortcutOps.Count)"
}
$badTestShortcutRefs = @($nsiRecords | Where-Object {
    $_.ActiveInTest -and -not $_.Text.Trim().StartsWith(';') -and (
        $_.Text -match '\$DESKTOP\\Sopeek\.lnk' -or
        $_.Text -match '\$SMPROGRAMS\\Sopeek(?:\\|")' -or
        $_.Text -match '\$SMPROGRAMS\\Sopeek\.lnk'
    )
})
if ($badTestShortcutRefs.Count -gt 0) {
    $detail = ($badTestShortcutRefs | ForEach-Object { "installer.nsi:$($_.LineNumber): $($_.Text.Trim())" }) -join "`n"
    throw "NSIS test-isolation assertion failed: test mode references a production shortcut path:`n$detail"
}

Write-Host ("NSIS static assertions: PASS ({0} active test-mode lines; {1} test registry ops; {2} test DeleteRegKey)" -f `
    @($nsiRecords | Where-Object { $_.ActiveInTest }).Count, $activeRegistryLines.Count, $testDeleteRegKey.Count)

# ---------------------------------------------------------------------------
# Rebuild the SPK_TESTMODE GUI (test-only output directory).
# ---------------------------------------------------------------------------
Write-Host "Build step 1/2: & `"$buildTestGui`""
& $buildTestGui
$guiBuildExit = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
if ($guiBuildExit -ne 0) {
    throw "build_test_gui.ps1 failed with exit code $guiBuildExit"
}
Write-Host "build_test_gui.ps1 exit code: $guiBuildExit"

$productionAfterGui = Get-ProductionSnapshots -Paths $productionPaths
Assert-ProductionUnchanged -Paths $productionPaths -Before $productionBefore -After $productionAfterGui -Stage 'build_test_gui.ps1'

if (-not (Test-Path -LiteralPath $testGui -PathType Leaf)) { throw "Missing test GUI: $testGui" }
if (-not (Test-Path -LiteralPath $testDll -PathType Leaf)) { throw "Missing test runtime DLL: $testDll" }
if (-not (Test-Path -LiteralPath $testGuiBuild -PathType Leaf)) { throw "Missing SPK_TESTMODE GUI build output: $testGuiBuild" }

$testGuiHash = (Get-FileHash -LiteralPath $testGui -Algorithm SHA256).Hash
$testGuiBuildHash = (Get-FileHash -LiteralPath $testGuiBuild -Algorithm SHA256).Hash
$testDllHash = (Get-FileHash -LiteralPath $testDll -Algorithm SHA256).Hash
$mingwDllHash = (Get-FileHash -LiteralPath $mingwDll -Algorithm SHA256).Hash

if ($testGuiHash -ne $testGuiBuildHash) {
    throw "Test GUI provenance failed: $testGui is not the SPK_TESTMODE output from $testGuiBuild"
}
if ($testDllHash -ne $mingwDllHash) {
    throw "Test runtime provenance failed: $testDll is not the MinGW libwinpthread-1.dll"
}

$productionGuiIndex = -1
for ($i = 0; $i -lt $productionPaths.Count; $i++) {
    if ([string]::Equals($productionPaths[$i], $productionGui, [System.StringComparison]::OrdinalIgnoreCase)) {
        $productionGuiIndex = $i
        break
    }
}
if ($productionGuiIndex -lt 0) { throw 'Internal error: production GUI path not in snapshot list' }
$productionGuiBefore = $productionBefore[$productionGuiIndex]
# Only comparable when the production GUI exists (clean checkouts legitimately
# have no production GUI; the test build itself must not create one).
if ($null -ne $productionGuiBefore -and $testGuiHash -eq $productionGuiBefore.SHA256) {
    throw "Test GUI provenance failed: test GUI hash equals the production GUI (test build did not use SPK_TESTMODE)"
}

Write-Host ("Test GUI   : {0} ({1} bytes) SHA256 {2}" -f $testGui, (Get-Item -LiteralPath $testGui).Length, $testGuiHash)
Write-Host ("Test DLL   : {0} ({1} bytes) SHA256 {2}" -f $testDll, (Get-Item -LiteralPath $testDll).Length, $testDllHash)

# ---------------------------------------------------------------------------
# Compile the isolated NSIS test setup.
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath $testSetup) {
    Remove-Item -LiteralPath $testSetup -Force
}

$makensisArgs = @(
    '/WX'
    '/DSPK_TESTMODE'
    "/DSPK_OUTFILE=$testSetup"
    $nsiPath
)
Write-Host "Build step 2/2: & `"$nsisExe`" $($makensisArgs -join ' ')"
$nsisOutput = & $nsisExe @makensisArgs 2>&1
$nsisExit = $LASTEXITCODE
$nsisText = ($nsisOutput | Out-String)
if ($nsisExit -ne 0) {
    throw "makensis failed with exit code $nsisExit`n$nsisText"
}
$warningMatches = [regex]::Matches($nsisText, '(?im)^\s*(?:warning|error)(?:\s+\d+)?\s*:')
if ($warningMatches.Count -gt 0) {
    throw "makensis reported warnings/errors (exit $nsisExit):`n$nsisText"
}
Write-Host "makensis exit code: $nsisExit (warnings-as-errors, no warning/error output)"

if (-not (Test-Path -LiteralPath $testSetup -PathType Leaf)) {
    throw "makensis did not produce the test setup: $testSetup"
}

# ---------------------------------------------------------------------------
# Test GUI dependency check (must not import the MSYS2 C++ runtime DLLs).
# ---------------------------------------------------------------------------
$objdumpOutput = & $objdumpExe -p $testGui 2>&1
$objdumpExit = $LASTEXITCODE
if ($objdumpExit -ne 0) {
    throw "objdump failed with exit code $objdumpExit`n$(($objdumpOutput | Out-String))"
}
$dllImports = @($objdumpOutput | Select-String -Pattern 'DLL Name' | ForEach-Object { $_.Line.Trim() })
$badImports = @($dllImports | Where-Object { $_ -match 'libgcc_s_seh-1|libstdc\+\+-6' })
if ($badImports.Count -gt 0) {
    throw "Test GUI still depends on the MSYS2 C++ runtime:`n$(($badImports) -join "`n")"
}
Write-Host ("objdump   : PASS ({0} imports; no libgcc_s_seh-1 / libstdc++-6)" -f $dllImports.Count)

# ---------------------------------------------------------------------------
# Final production check + summary.
# ---------------------------------------------------------------------------
$productionAfter = Get-ProductionSnapshots -Paths $productionPaths
Assert-ProductionUnchanged -Paths $productionPaths -Before $productionBefore -After $productionAfter -Stage 'makensis'

$setupItem = Get-Item -LiteralPath $testSetup
$setupHash = (Get-FileHash -LiteralPath $testSetup -Algorithm SHA256).Hash
$sizeMiB = [math]::Round($setupItem.Length / 1MB, 2)

Write-Host ''
Write-Host 'T18 test setup build complete.'
Write-Host "  Test setup : $($setupItem.FullName)"
Write-Host ("  Size       : {0} bytes ({1} MiB)" -f $setupItem.Length, $sizeMiB)
Write-Host "  SHA256     : $setupHash"
Write-Host "  Test GUI   : $testGuiHash"
Write-Host "  Test DLL   : $testDllHash"
Write-Host '  Production artifacts unchanged:'
for ($i = 0; $i -lt $productionPaths.Count; $i++) {
    $snapshot = $productionAfter[$i]
    if ($null -eq $snapshot) {
        Write-Host ("    {0}`n      ABSENT before and after (not created by test build)" -f $productionPaths[$i])
    }
    else {
        Write-Host ("    {0}`n      SHA256 {1}  size {2}  mtime {3:o}" -f $snapshot.Path, $snapshot.SHA256, $snapshot.Length, $snapshot.LastWriteTimeUtc)
    }
}
