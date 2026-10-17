#requires -Version 7.0
<#
.SYNOPSIS
  Todo 20 stub payload generator (dev-only tool; NOT part of the production chain).

.DESCRIPTION
  Recreates a deterministic stub payload used by `capture_installer.ps1` runs of
  the test build (`build/test-installer/FreeAssetFilterInstaller.exe`,
  FAF_TESTMODE=ON) driven by /auto.

  - Always wipes and recreates -PayloadDir.
  - Writes -FileCount deterministic files of -BytesPerFile bytes spread over the
    payload root plus -SubDirs subdirectories (sub00, sub01, ...).
  - Installs the install-engine sentinel `payload.ready` in the PARENT directory
    of -PayloadDir (plan §11: PayloadSentinelPath = payload.parent_path()/payload.ready).
  - With -NoSentinel the sentinel is removed instead: the engine then holds on
    the Progress page at 0% until its timeout (used for the deterministic
    Progress screenshot).

.EXAMPLE
  ./make_stub_payload.ps1 -PayloadDir C:\Users\89553\AppData\Local\Temp\opencode\faf_t20\payload
  ./make_stub_payload.ps1 -PayloadDir C:\Users\89553\AppData\Local\Temp\opencode\faf_t20\payload -NoSentinel
#>
param(
    [Parameter(Mandatory = $true)][string]$PayloadDir,
    [ValidateRange(1, 1000)][int]$FileCount = 24,
    [ValidateRange(0, 16)][int]$SubDirs = 3,
    [ValidateRange(4, 1048576)][int]$BytesPerFile = 8192,
    [switch]$NoSentinel
)

$ErrorActionPreference = 'Stop'

$full = [System.IO.Path]::GetFullPath($PayloadDir)
if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Recurse -Force }
New-Item -ItemType Directory -Force -Path $full | Out-Null

$dirs = @($full)
for ($d = 0; $d -lt $SubDirs; $d++) {
    $sub = Join-Path $full ('sub{0:D2}' -f $d)
    New-Item -ItemType Directory -Force -Path $sub | Out-Null
    $dirs += $sub
}

$total = 0L
for ($i = 0; $i -lt $FileCount; $i++) {
    $target = $dirs[$i % $dirs.Count]
    $path = Join-Path $target ('stub-{0:D3}.bin' -f $i)
    $buf = New-Object byte[] $BytesPerFile
    for ($b = 0; $b -lt $BytesPerFile; $b++) { $buf[$b] = [byte](($i * 31 + $b * 7) % 251) }
    [System.IO.File]::WriteAllBytes($path, $buf)
    $total += $BytesPerFile
}

$sentinel = Join-Path (Split-Path $full -Parent) 'payload.ready'
if ($NoSentinel) {
    Remove-Item -LiteralPath $sentinel -Force -ErrorAction SilentlyContinue
    $sentinelState = 'absent'
} else {
    [System.IO.File]::WriteAllText($sentinel, "[ready]`r`nready=1`r`n", (New-Object System.Text.UTF8Encoding($false)))
    $sentinelState = "present ($sentinel)"
}

Write-Host ('[STUB] payload={0} files={1} dirs={2} bytes={3} sentinel={4}' -f $full, $FileCount, ($SubDirs + 1), $total, $sentinelState)
