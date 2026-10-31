<#
.SYNOPSIS
    Three-surface legacy-brand gate.

.DESCRIPTION
    Runs three independent checks against the tree rooted at -Root:

      1. TEXT CONTENT
         Every non-excluded file (dotfiles included, no extension filtering)
         is read and decoded as UTF-8 BOM, UTF-16LE BOM, UTF-16BE BOM,
         strict UTF-8, or NUL-heavy UTF-16LE. Files that cannot be decoded
         are listed in skipped[] and do not count as hits.

      2. FILE AND DIRECTORY NAMES
         Matches only $_.Name, never an absolute path. Every reported path
         and every exclusion is evaluated relative to -Root, so a checkout
         directory whose own name contains a legacy token is never a hit.
         The repository root itself is never tested.

      3. BUILD ARTIFACTS (opt-in)
         Raw-byte ASCII plus UTF-16LE scan of fresh build outputs using
         long-form identifiers only. Bare three-letter short tokens are
         deliberately NOT used for binary scans. Missing artifact paths are
         recorded in missing_artifacts[] without failing the gate.

    The forbidden patterns are assembled from string fragments at runtime so
    this script never matches itself. The effective patterns are echoed into
    gate.json for auditability.

    Exit codes: 0 = clean, 1 = at least one non-allowlisted hit,
                2 = usage error.

.PARAMETER Root
    Tree root. Defaults to the parent directory of this script.

.PARAMETER IncludeBuildArtifacts
    Also scan the standard fresh build artifact locations.

.PARAMETER ArtifactsOnly
    Skip the text surface. Run the name surface and the binary artifact
    surface only over the paths supplied with -ArtifactPaths.

.PARAMETER ArtifactPaths
    Comma-separated file or directory paths. Relative paths are resolved
    against -Root. Directories are walked recursively for artifact scans.

.PARAMETER Json
    Write gate.json to this path. Without -Json the JSON is printed to stdout.

.NOTES
    Windows PowerShell 5.1 compatible. No git commands are executed. No
    excluded directory (such as .git/ or mirror trees) is ever enumerated.
#>
[CmdletBinding()]
param(
    [string]$Root = '',
    [switch]$IncludeBuildArtifacts,
    [switch]$ArtifactsOnly,
    [string]$ArtifactPaths = '',
    [string]$Json = ''
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = Split-Path -Parent $PSScriptRoot
}
$Root = (Resolve-Path -LiteralPath $Root).ProviderPath
$Root = $Root.TrimEnd('\', '/')

if ($ArtifactsOnly -and [string]::IsNullOrWhiteSpace($ArtifactPaths)) {
    Write-Output '-ArtifactsOnly requires -ArtifactPaths.'
    exit 2
}

# ---------------------------------------------------------------------------
# Frozen exclusion manifest (identical to T1, case-insensitive). Directory
# patterns are tested before recursion, so excluded trees are never walked.
# ---------------------------------------------------------------------------
$ExclusionManifest = @(
    '.git/',
    '.venv/',
    '.probe_venv/',
    '.probe_head_tree/',
    '.kilo/',
    '.trae/',
    '.zcode/',
    '.workbuddy/',
    '.qoder/',
    '.continue/',
    '.agents/',
    '.codegraph/',
    '.acl-recovery/',
    '.dsh-acl-recovery/',
    '.demo_out/',
    '.pytest_tmp/',
    '.VSCodeCounter/',
    'outputs/',
    'tests/log/',
    'build/',
    'dist/',
    'data/',
    '.omo/',
    'node_modules/',
    '__pycache__/',
    '*/target/',
    '*/build/',
    '.ruff_cache/',
    '.pytest_cache/',
    '.coverage',
    '.opencode/',
    '.reasonix/'
)

# Directories never descended into during explicit artifact walks. This is a
# safety net only; it intentionally does not contain build/ or dist/, because
# artifact scans are supposed to inspect those trees when supplied.
$ArtifactSkipNames = @(
    '.git',
    '.venv',
    '.probe_venv',
    '.probe_head_tree',
    '.kilo',
    '.omo',
    'node_modules',
    '__pycache__'
)

# ---------------------------------------------------------------------------
# Pattern assembly. Fragments keep the forbidden literals out of this file's
# own bytes while the runtime patterns are exactly the required ones.
#
# Effective text pattern (assembled at runtime):
#   the brand word (case-insensitive, optional separators),
#   OR the three-letter short token with leading/trailing boundaries,
#   OR the version token with word boundaries.
# The fragments below reproduce the required pattern exactly.
# ---------------------------------------------------------------------------
$brandLower = 'free' + 'asset' + 'filter'
$shortTok = 'f' + 'af'
$shortTokUpper = 'FA' + 'F'
$triClass = '[Ff]' + '[Aa]' + '[Ff]'

$TextPattern = '(?:(?i:' + $brandLower + '|free[\s_-]*asset[\s_-]*filter)' +
    '|(?<![A-Za-z0-9])' + $triClass + '(?=[A-Z_]|[_\-.\\/]|\b)' +
    '|\b' + $shortTok + 'version\b)'
$TextRegex = New-Object System.Text.RegularExpressions.Regex -ArgumentList $TextPattern

# Binary long-form identifiers. No bare short token is present here.
$binFreeMixed = 'Free' + 'Asset' + 'Filter'
$binFreeSpaced = 'Free ' + 'Asset ' + 'Filter'
$binAlternatives = @(
    $binFreeMixed,
    $binFreeSpaced,
    ($shortTokUpper + 'VERSION'),
    ($shortTok + 'version'),
    ($shortTok + '_core'),
    ($shortTok + '_updater'),
    ($shortTok + '_core_fixtures'),
    ($shortTokUpper + '-main'),
    ($shortTokUpper + '-setup'),
    ($shortTokUpper + '-Launcher'),
    ($shortTokUpper + '_TESTMODE'),
    ($shortTokUpper + '_DATA_DIR'),
    ($shortTokUpper + '_OUTFILE'),
    ('IDR_' + $shortTokUpper + 'VERSION'),
    ($shortTokUpper + '_GPU_LAUNCHED'),
    ($shortTokUpper + '_GPU_PARENT_PID'),
    ($shortTokUpper + '_LAUNCHER_CMD')
)
$BinaryPattern = '(?i:' + ($binAlternatives -join '|') + ')'
$BinaryRegex = New-Object System.Text.RegularExpressions.Regex -ArgumentList $BinaryPattern

$Latin1 = [System.Text.Encoding]::GetEncoding(28591)
$Utf16Loose = New-Object System.Text.UnicodeEncoding -ArgumentList $false, $false, $false

# Raw artifact scans are chunked so a large installer does not have to be
# materialized as one huge string. The overlap exceeds the longest binary
# pattern, and a per-surface start-index set prevents boundary duplicates.
$script:BinaryChunkSize = 4MB
$script:BinaryOverlap = 64

# ---------------------------------------------------------------------------
# Script-scope accumulator state.
# ---------------------------------------------------------------------------
$script:FilesScanned = 0
$script:TextHits = 0
$script:TextHitFiles = 0
$script:NameHits = 0
$script:NameFilesExamined = 0
$script:NameDirsExamined = 0
$script:BinaryHits = 0
$script:BinaryArtifactsScanned = 0
$script:SkippedBinary = 0
$script:ReadErrors = 0
$script:DirectoryCount = 0

$script:TextHitDetails = New-Object System.Collections.Generic.List[object]
$script:NameFileHits = New-Object System.Collections.Generic.List[object]
$script:NameDirHits = New-Object System.Collections.Generic.List[object]
$script:BinaryHitDetails = New-Object System.Collections.Generic.List[object]
$script:Skipped = New-Object System.Collections.Generic.List[object]
$script:SkippedDirs = New-Object System.Collections.Generic.List[object]
$script:DirectoryErrors = New-Object System.Collections.Generic.List[object]
$script:ArtifactPathsRequested = New-Object System.Collections.Generic.List[string]
$script:ArtifactsScanned = New-Object System.Collections.Generic.List[string]
$script:MissingArtifacts = New-Object System.Collections.Generic.List[string]
$script:ArtifactErrors = New-Object System.Collections.Generic.List[object]

# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------
function Test-ExcludedPath {
    param(
        [string]$RelPath,
        [bool]$IsDirectory
    )
    $rel = $RelPath.Replace('\', '/').ToLowerInvariant()
    if ($rel.Length -eq 0) { return $false }
    foreach ($raw in $ExclusionManifest) {
        $p = $raw.ToLowerInvariant()
        if ($p.EndsWith('/')) {
            if (-not $IsDirectory) { continue }
            $p = $p.TrimEnd('/')
            if ($p.StartsWith('*/')) {
                $suffix = $p.Substring(2)
                if ($rel -eq $suffix -or $rel.EndsWith('/' + $suffix)) { return $true }
            }
            elseif ($p.Contains('/')) {
                if ($rel -eq $p -or $rel.StartsWith($p + '/')) { return $true }
            }
            else {
                if ($rel -eq $p -or $rel.EndsWith('/' + $p) -or $rel.Contains('/' + $p + '/')) { return $true }
            }
        }
        else {
            if (-not $IsDirectory) {
                $name = $rel.Substring($rel.LastIndexOf('/') + 1)
                if ($name -eq $p) { return $true }
            }
        }
    }
    return $false
}

function Get-RootRelativePath {
    param([string]$FullPath)
    if ($FullPath.Equals($script:Root, [System.StringComparison]::OrdinalIgnoreCase)) { return '' }
    $prefix = $script:Root + [System.IO.Path]::DirectorySeparatorChar
    if ($FullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $FullPath.Substring($script:Root.Length).TrimStart('\', '/').Replace('\', '/')
    }
    return $FullPath.Replace('\', '/')
}

function Test-NulHeavyBytes {
    param([byte[]]$Bytes)
    $n = $Bytes.Length
    $sample = [Math]::Min($n, 4096)
    if ($sample -lt 8) { return $false }
    $pairs = [int][Math]::Floor($sample / 2)
    $zeroCount = 0
    $highZeroCount = 0
    for ($i = 0; $i -lt ($pairs * 2); $i += 2) {
        if ($Bytes[$i] -eq 0) { $zeroCount++ }
        if ($Bytes[$i + 1] -eq 0) {
            $zeroCount++
            $highZeroCount++
        }
    }
    $zeroRatio = [double]$zeroCount / [double]($pairs * 2)
    $highZeroRatio = [double]$highZeroCount / [double]$pairs
    return ($zeroRatio -ge 0.10 -and $highZeroRatio -ge 0.90)
}

function Convert-BytesToText {
    param([byte[]]$Bytes)
    $n = $Bytes.Length
    if ($n -eq 0) {
        return @{ Ok = $true; Text = ''; Encoding = 'empty'; Reason = '' }
    }
    if ($n -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF) {
        try {
            $enc = New-Object System.Text.UTF8Encoding -ArgumentList $false, $true
            return @{ Ok = $true; Text = $enc.GetString($Bytes, 3, $n - 3); Encoding = 'utf-8-bom'; Reason = '' }
        }
        catch {
            return @{ Ok = $false; Text = $null; Encoding = $null; Reason = 'utf-8-bom-decode-error' }
        }
    }
    if ($n -ge 2 -and $Bytes[0] -eq 0xFF -and $Bytes[1] -eq 0xFE) {
        try {
            $enc = New-Object System.Text.UnicodeEncoding -ArgumentList $false, $false, $true
            return @{ Ok = $true; Text = $enc.GetString($Bytes, 2, $n - 2); Encoding = 'utf-16le-bom'; Reason = '' }
        }
        catch {
            return @{ Ok = $false; Text = $null; Encoding = $null; Reason = 'utf-16le-bom-decode-error' }
        }
    }
    if ($n -ge 2 -and $Bytes[0] -eq 0xFE -and $Bytes[1] -eq 0xFF) {
        try {
            $enc = New-Object System.Text.UnicodeEncoding -ArgumentList $true, $false, $true
            return @{ Ok = $true; Text = $enc.GetString($Bytes, 2, $n - 2); Encoding = 'utf-16be-bom'; Reason = '' }
        }
        catch {
            return @{ Ok = $false; Text = $null; Encoding = $null; Reason = 'utf-16be-bom-decode-error' }
        }
    }
    # Strict UTF-8 is attempted first. Some genuine UTF-8 text contains NUL
    # bytes, but ASCII UTF-16LE is also valid UTF-8 (every high byte is NUL).
    # When the NUL pattern is decisive, reinterpret the bytes as UTF-16LE so a
    # BOM-less UTF-16LE file cannot slip through as decoded-looking text.
    $nulHeavy = Test-NulHeavyBytes -Bytes $Bytes

    try {
        $enc = New-Object System.Text.UTF8Encoding -ArgumentList $false, $true
        $utf8Text = $enc.GetString($Bytes)
        if ($nulHeavy) {
            try {
                $u16 = New-Object System.Text.UnicodeEncoding -ArgumentList $false, $false, $true
                return @{ Ok = $true; Text = $u16.GetString($Bytes); Encoding = 'utf-16le-heuristic'; Reason = '' }
            }
            catch {
                # keep the strict UTF-8 decoding
            }
        }
        return @{ Ok = $true; Text = $utf8Text; Encoding = 'utf-8'; Reason = '' }
    }
    catch {
        # fall through to the NUL-heavy UTF-16LE heuristic
    }

    if ($nulHeavy) {
        try {
            $enc = New-Object System.Text.UnicodeEncoding -ArgumentList $false, $false, $true
            return @{ Ok = $true; Text = $enc.GetString($Bytes); Encoding = 'utf-16le-heuristic'; Reason = '' }
        }
        catch {
            # fall through to undecodable
        }
    }
    return @{ Ok = $false; Text = $null; Encoding = $null; Reason = 'undecodable-binary' }
}

function Get-LineStarts {
    param([string]$Text)
    $starts = New-Object System.Collections.Generic.List[int]
    [void]$starts.Add(0)
    for ($i = 0; $i -lt $Text.Length; $i++) {
        if ($Text[$i] -eq [char]10) { [void]$starts.Add($i + 1) }
    }
    return $starts.ToArray()
}

function Find-LineNumber {
    param([int[]]$Starts, [int]$Index)
    $lo = 0
    $hi = $Starts.Length - 1
    while ($lo -lt $hi) {
        $mid = [int][Math]::Floor(($lo + $hi + 1) / 2)
        if ($Starts[$mid] -le $Index) { $lo = $mid } else { $hi = $mid - 1 }
    }
    return $lo + 1
}

function Add-TextFileHits {
    param(
        [string]$Text,
        [string]$RelPath,
        [string]$Encoding
    )
    $matches = $script:TextRegex.Matches($Text)
    if ($matches.Count -eq 0) { return }
    $starts = $null
    foreach ($m in $matches) {
        if ($null -eq $starts) { $starts = Get-LineStarts -Text $Text }
        $script:TextHits++
        [void]$script:TextHitDetails.Add([ordered]@{
            path = $RelPath
            line = (Find-LineNumber -Starts $starts -Index $m.Index)
            match = $m.Value
            encoding = $Encoding
        })
    }
    $script:TextHitFiles++
}

function Add-NameHit {
    param(
        [System.Collections.Generic.List[object]]$Target,
        [string]$Name,
        [string]$RelPath
    )
    $matches = $script:TextRegex.Matches($Name)
    if ($matches.Count -gt 0) {
        [void]$Target.Add([ordered]@{
            path = $RelPath
            name = $Name
            hits = $matches.Count
        })
        return $matches.Count
    }
    return 0
}

function Add-BinaryFileHits {
    param(
        [string]$FullPath,
        [string]$RelPath
    )
    try {
        $bytes = [System.IO.File]::ReadAllBytes($FullPath)
    }
    catch {
        [void]$script:ArtifactErrors.Add([ordered]@{
            path = $RelPath
            error = $_.Exception.Message
        })
        $script:ReadErrors++
        return
    }

    $script:BinaryArtifactsScanned++
    [void]$script:ArtifactsScanned.Add($RelPath)

    $n = $bytes.Length
    $chunkSize = $script:BinaryChunkSize
    $overlap = $script:BinaryOverlap

    # ASCII / raw-byte surface.
    $seenAscii = New-Object 'System.Collections.Generic.HashSet[int]'
    $pos = 0
    while ($pos -lt $n) {
        $len = [Math]::Min($chunkSize + $overlap, $n - $pos)
        $chunk = $Latin1.GetString($bytes, $pos, $len)
        foreach ($m in $BinaryRegex.Matches($chunk)) {
            $abs = $pos + $m.Index
            if ($seenAscii.Add($abs)) {
                $script:BinaryHits++
                [void]$script:BinaryHitDetails.Add([ordered]@{
                    path = $RelPath
                    match = $m.Value
                    surface = 'ascii'
                })
            }
        }
        if (($pos + $chunkSize) -ge $n) { break }
        $pos += $chunkSize
    }

    # UTF-16LE surface, aligned to two-byte code units.
    if ($n -ge 2) {
        $seenUtf16 = New-Object 'System.Collections.Generic.HashSet[int]'
        $pos = 0
        while ($pos -lt ($n - 1)) {
            $len = [Math]::Min($chunkSize + $overlap, $n - $pos)
            $len = $len - ($len % 2)
            if ($len -le 0) { break }
            $text = $Utf16Loose.GetString($bytes, $pos, $len)
            foreach ($m in $BinaryRegex.Matches($text)) {
                $abs = $pos + ($m.Index * 2)
                if ($seenUtf16.Add($abs)) {
                    $script:BinaryHits++
                    [void]$script:BinaryHitDetails.Add([ordered]@{
                        path = $RelPath
                        match = $m.Value
                        surface = 'utf-16le'
                    })
                }
            }
            if (($pos + $chunkSize) -ge ($n - 1)) { break }
            $pos += $chunkSize
        }
    }
}

# ---------------------------------------------------------------------------
# Surface 1 + 2: full tree walk. Excluded directories are filtered before
# Push, so their contents are never enumerated.
# ---------------------------------------------------------------------------
function Invoke-TreeScan {
    $stack = New-Object 'System.Collections.Generic.Stack[string]'
    $stack.Push($script:Root)

    while ($stack.Count -gt 0) {
        $current = $stack.Pop()
        try {
            $children = @(Get-ChildItem -LiteralPath $current -Force -ErrorAction Stop)
        }
        catch {
            [void]$script:DirectoryErrors.Add([ordered]@{
                path = (Get-RootRelativePath $current)
                error = $_.Exception.Message
            })
            continue
        }
        $children = @($children | Sort-Object -Property Name)

        foreach ($child in $children) {
            $rel = Get-RootRelativePath $child.FullName

            if ($child.PSIsContainer) {
                if (Test-ExcludedPath -RelPath $rel -IsDirectory $true) { continue }
                $isReparse = (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
                if ($isReparse) {
                    [void]$script:SkippedDirs.Add([ordered]@{ path = $rel; reason = 'reparse-point' })
                    continue
                }
                $script:DirectoryCount++
                $script:NameDirsExamined++
                $script:NameHits += (Add-NameHit -Target $script:NameDirHits -Name $child.Name -RelPath $rel)
                $stack.Push($child.FullName)
                continue
            }

            if (Test-ExcludedPath -RelPath $rel -IsDirectory $false) { continue }

            $script:FilesScanned++
            $script:NameFilesExamined++
            $script:NameHits += (Add-NameHit -Target $script:NameFileHits -Name $child.Name -RelPath $rel)

            try {
                $bytes = [System.IO.File]::ReadAllBytes($child.FullName)
            }
            catch {
                [void]$script:Skipped.Add([ordered]@{
                    surface = 'text'
                    path = $rel
                    bytes = [int64]$child.Length
                    reason = 'read-error'
                    detail = $_.Exception.Message
                })
                $script:ReadErrors++
                continue
            }

            $decoded = Convert-BytesToText -Bytes $bytes
            if (-not $decoded.Ok) {
                [void]$script:Skipped.Add([ordered]@{
                    surface = 'text'
                    path = $rel
                    bytes = [int64]$bytes.Length
                    reason = $decoded.Reason
                    detail = ''
                })
                $script:SkippedBinary++
                continue
            }

            Add-TextFileHits -Text $decoded.Text -RelPath $rel -Encoding $decoded.Encoding
        }
    }
}

# ---------------------------------------------------------------------------
# Surface 3: artifact expansion and raw-byte scan.
# ---------------------------------------------------------------------------
function Add-ArtifactEntries {
    param(
        [string]$SpecPath,
        [string]$Kind,
        [System.Collections.Generic.List[object]]$FileEntries,
        [System.Collections.Generic.List[object]]$NameEntries
    )

    $display = Get-RootRelativePath $SpecPath
    if (-not (Test-Path -LiteralPath $SpecPath)) {
        [void]$script:MissingArtifacts.Add($display)
        return
    }

    try {
        $item = Get-Item -LiteralPath $SpecPath -Force -ErrorAction Stop
    }
    catch {
        [void]$script:ArtifactErrors.Add([ordered]@{ path = $display; error = $_.Exception.Message })
        return
    }

    if (-not $item.PSIsContainer) {
        if ($null -ne $NameEntries) {
            [void]$NameEntries.Add([ordered]@{ path = $display; name = $item.Name; is_directory = $false })
        }
        [void]$FileEntries.Add([ordered]@{ full = $item.FullName; rel = $display })
        return
    }

    if ($null -ne $NameEntries) {
        [void]$NameEntries.Add([ordered]@{ path = $display; name = $item.Name; is_directory = $true })
    }

    # 'exe' and 'native' specs use a single '*' (direct children only).
    # 'dir' and 'path' specs recurse.
    $directOnly = ($Kind -eq 'exe' -or $Kind -eq 'native')

    if ($directOnly) {
        try {
            $children = @(Get-ChildItem -LiteralPath $item.FullName -Force -ErrorAction Stop)
        }
        catch {
            [void]$script:ArtifactErrors.Add([ordered]@{
                path = $display
                error = $_.Exception.Message
            })
            return
        }
        $children = @($children | Sort-Object -Property Name)
        foreach ($child in $children) {
            if ($child.PSIsContainer) { continue }
            $include = $true
            if ($Kind -eq 'exe') {
                if ($child.Extension -ine '.exe') { $include = $false }
            }
            elseif ($Kind -eq 'native') {
                if ($child.Extension -ine '.dll' -and $child.Extension -ine '.exe') { $include = $false }
            }
            if (-not $include) { continue }

            $rel = Get-RootRelativePath $child.FullName
            if ($null -ne $NameEntries) {
                [void]$NameEntries.Add([ordered]@{ path = $rel; name = $child.Name; is_directory = $false })
            }
            [void]$FileEntries.Add([ordered]@{ full = $child.FullName; rel = $rel })
        }
        return
    }

    $stack = New-Object 'System.Collections.Generic.Stack[string]'
    $stack.Push($item.FullName)
    while ($stack.Count -gt 0) {
        $current = $stack.Pop()
        try {
            $children = @(Get-ChildItem -LiteralPath $current -Force -ErrorAction Stop)
        }
        catch {
            [void]$script:ArtifactErrors.Add([ordered]@{
                path = (Get-RootRelativePath $current)
                error = $_.Exception.Message
            })
            continue
        }
        $children = @($children | Sort-Object -Property Name)

        foreach ($child in $children) {
            $rel = Get-RootRelativePath $child.FullName
            if ($child.PSIsContainer) {
                if ($ArtifactSkipNames -contains $child.Name) { continue }
                $isReparse = (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
                if ($isReparse) { continue }
                if ($null -ne $NameEntries) {
                    [void]$NameEntries.Add([ordered]@{ path = $rel; name = $child.Name; is_directory = $true })
                }
                $stack.Push($child.FullName)
                continue
            }

            if ($null -ne $NameEntries) {
                [void]$NameEntries.Add([ordered]@{ path = $rel; name = $child.Name; is_directory = $false })
            }
            [void]$FileEntries.Add([ordered]@{ full = $child.FullName; rel = $rel })
        }
    }
}

function Resolve-ArtifactSpecPath {
    param([string]$Spec)
    $trimmed = $Spec.Trim().Trim('"')
    if ([string]::IsNullOrWhiteSpace($trimmed)) { return '' }
    if ([System.IO.Path]::IsPathRooted($trimmed)) { return $trimmed }
    return (Join-Path $script:Root $trimmed)
}

function Invoke-ArtifactScan {
    param(
        [System.Collections.Generic.List[object]]$Specs,
        [bool]$RunNameScan
    )

    $fileEntries = New-Object System.Collections.Generic.List[object]
    $nameEntries = $null
    if ($RunNameScan) {
        $nameEntries = New-Object System.Collections.Generic.List[object]
    }

    foreach ($spec in $Specs) {
        [void]$script:ArtifactPathsRequested.Add($spec.label)
        try {
            Add-ArtifactEntries -SpecPath $spec.path -Kind $spec.kind -FileEntries $fileEntries -NameEntries $nameEntries
        }
        catch {
            [void]$script:ArtifactErrors.Add([ordered]@{
                path = $spec.label
                error = $_.Exception.Message
            })
        }
    }

    if ($RunNameScan) {
        $seenNames = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
        foreach ($entry in $nameEntries) {
            if (-not $seenNames.Add($entry.path)) { continue }
            if ($entry.is_directory) {
                $script:NameDirsExamined++
                $script:NameHits += (Add-NameHit -Target $script:NameDirHits -Name $entry.name -RelPath $entry.path)
            }
            else {
                $script:NameFilesExamined++
                $script:NameHits += (Add-NameHit -Target $script:NameFileHits -Name $entry.name -RelPath $entry.path)
            }
        }
    }

    $seenFiles = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in $fileEntries) {
        if (-not $seenFiles.Add($entry.full)) { continue }
        Add-BinaryFileHits -FullPath $entry.full -RelPath $entry.rel
    }
}

# ---------------------------------------------------------------------------
# Mode dispatch.
# ---------------------------------------------------------------------------
if ($ArtifactsOnly) {
    $supplied = New-Object System.Collections.Generic.List[object]
    foreach ($piece in ($ArtifactPaths -split ',')) {
        $resolved = Resolve-ArtifactSpecPath -Spec $piece
        if ([string]::IsNullOrWhiteSpace($resolved)) { continue }
        [void]$supplied.Add([ordered]@{
            label = (Get-RootRelativePath $resolved)
            path = $resolved
            kind = 'path'
        })
    }
    Invoke-ArtifactScan -Specs $supplied -RunNameScan $true
    $mode = 'artifacts-only'
}
else {
    Invoke-TreeScan

    if ($IncludeBuildArtifacts) {
        $defaultSpecs = New-Object System.Collections.Generic.List[object]
        [void]$defaultSpecs.Add([ordered]@{
            label = 'build/pyinstall/Sopeek'
            path = (Join-Path $Root 'build/pyinstall/Sopeek')
            kind = 'dir'
        })
        [void]$defaultSpecs.Add([ordered]@{
            label = 'build/installer'
            path = (Join-Path $Root 'build/installer')
            kind = 'dir'
        })
        [void]$defaultSpecs.Add([ordered]@{
            label = 'build/*.exe'
            path = (Join-Path $Root 'build')
            kind = 'exe'
        })
        [void]$defaultSpecs.Add([ordered]@{
            label = 'launcher/SPK-Launcher.exe'
            path = (Join-Path $Root 'launcher/SPK-Launcher.exe')
            kind = 'file'
        })
        [void]$defaultSpecs.Add([ordered]@{
            label = 'sopeek/core/native/bin/*.dll|*.exe'
            path = (Join-Path $Root 'sopeek/core/native/bin')
            kind = 'native'
        })

        if (-not [string]::IsNullOrWhiteSpace($ArtifactPaths)) {
            foreach ($piece in ($ArtifactPaths -split ',')) {
                $resolved = Resolve-ArtifactSpecPath -Spec $piece
                if ([string]::IsNullOrWhiteSpace($resolved)) { continue }
                [void]$defaultSpecs.Add([ordered]@{
                    label = (Get-RootRelativePath $resolved)
                    path = $resolved
                    kind = 'path'
                })
            }
        }
        Invoke-ArtifactScan -Specs $defaultSpecs -RunNameScan $false
    }
    elseif (-not [string]::IsNullOrWhiteSpace($ArtifactPaths)) {
        $supplied = New-Object System.Collections.Generic.List[object]
        foreach ($piece in ($ArtifactPaths -split ',')) {
            $resolved = Resolve-ArtifactSpecPath -Spec $piece
            if ([string]::IsNullOrWhiteSpace($resolved)) { continue }
            [void]$supplied.Add([ordered]@{
                label = (Get-RootRelativePath $resolved)
                path = $resolved
                kind = 'path'
            })
        }
        Invoke-ArtifactScan -Specs $supplied -RunNameScan $false
    }
    $mode = 'full'
}

# ---------------------------------------------------------------------------
# Deterministic ordering and aggregation.
# ---------------------------------------------------------------------------
$textDetails = @($script:TextHitDetails | Sort-Object -Property @{ Expression = { $_.path } }, @{ Expression = { $_.line } }, @{ Expression = { $_.match } })
$nameFileDetails = @($script:NameFileHits | Sort-Object -Property @{ Expression = { $_.path } })
$nameDirDetails = @($script:NameDirHits | Sort-Object -Property @{ Expression = { $_.path } })
$binaryDetails = @($script:BinaryHitDetails | Sort-Object -Property @{ Expression = { $_.path } }, @{ Expression = { $_.match } }, @{ Expression = { $_.surface } })
$skippedDetails = @($script:Skipped | Sort-Object -Property @{ Expression = { $_.path } })
$skippedDirDetails = @($script:SkippedDirs | Sort-Object -Property @{ Expression = { $_.path } })
$dirErrorDetails = @($script:DirectoryErrors | Sort-Object -Property @{ Expression = { $_.path } })
$artifactErrorDetails = @($script:ArtifactErrors | Sort-Object -Property @{ Expression = { $_.path } })
$artifactPathList = @($script:ArtifactPathsRequested | Sort-Object)
$artifactsScannedList = @($script:ArtifactsScanned | Sort-Object)
$missingArtifactList = @($script:MissingArtifacts | Sort-Object)

$totalHits = $script:TextHits + $script:NameHits + $script:BinaryHits

$gate = [ordered]@{
    schema = 'legacy-brand-gate-t2-v1'
    mode = $mode
    root = $Root
    root_name = (Split-Path -Leaf $Root)
    text_regex = $TextPattern
    binary_regex = $BinaryPattern
    exclusion_manifest = @($ExclusionManifest)
    decoder_order = @(
        'utf-8-bom',
        'utf-16le-bom',
        'utf-16be-bom',
        'utf-8-strict',
        'utf-16le-heuristic (NUL-heavy: >=10% zero bytes and >=90% zero high bytes in first 4096 bytes; applied even when strict UTF-8 succeeds)',
        'skip-as-undecodable'
    )
    files_scanned = $script:FilesScanned
    text_hits = $script:TextHits
    text_hit_files = $script:TextHitFiles
    name_hits = $script:NameHits
    name_hit_files = $nameFileDetails.Count
    name_hit_directories = $nameDirDetails.Count
    name_files_examined = $script:NameFilesExamined
    name_directories_examined = $script:NameDirsExamined
    binary_hits = $script:BinaryHits
    binary_artifacts_scanned = $script:BinaryArtifactsScanned
    hits = $totalHits
    skipped_binary = $script:SkippedBinary
    skipped_read_errors = $script:ReadErrors
    skipped = @($skippedDetails)
    skipped_directories = @($skippedDirDetails)
    directory_errors = @($dirErrorDetails)
    directory_count = $script:DirectoryCount
    text_hit_details = @($textDetails)
    name_hits_files = @($nameFileDetails)
    name_hits_directories = @($nameDirDetails)
    binary_hit_details = @($binaryDetails)
    artifact_paths = @($artifactPathList)
    artifacts_scanned = @($artifactsScannedList)
    missing_artifacts = @($missingArtifactList)
    artifact_errors = @($artifactErrorDetails)
}

$jsonText = $gate | ConvertTo-Json -Depth 10

if (-not [string]::IsNullOrWhiteSpace($Json)) {
    $jsonParent = Split-Path -Parent $Json
    if (-not [string]::IsNullOrWhiteSpace($jsonParent) -and -not (Test-Path -LiteralPath $jsonParent)) {
        New-Item -ItemType Directory -Path $jsonParent -Force | Out-Null
    }
    Set-Content -LiteralPath $Json -Value $jsonText -Encoding utf8
}

# ---------------------------------------------------------------------------
# Reporting. Every hit is printed, then the JSON (stdout mode) or a summary.
# ---------------------------------------------------------------------------
foreach ($hit in $textDetails) {
    $safeMatch = $hit.match.Replace("`r", '\r').Replace("`n", '\n')
    Write-Output ($hit.path + ':' + $hit.line + ':' + $safeMatch)
}
foreach ($hit in $nameFileDetails) {
    Write-Output ($hit.path + ':name:' + $hit.name)
}
foreach ($hit in $nameDirDetails) {
    Write-Output ($hit.path + ':dirname:' + $hit.name)
}
foreach ($hit in $binaryDetails) {
    Write-Output ($hit.path + ':binary:' + $hit.match + ' [' + $hit.surface + ']')
}

if ([string]::IsNullOrWhiteSpace($Json)) {
    Write-Output $jsonText
}
else {
    Write-Output ('legacy-brand gate: hits={0} text={1} name={2} binary={3} files_scanned={4} binary_artifacts_scanned={5} skipped_binary={6}' -f `
        $totalHits, $script:TextHits, $script:NameHits, $script:BinaryHits, $script:FilesScanned, $script:BinaryArtifactsScanned, $script:SkippedBinary)
    Write-Output ('json: ' + $Json)
}

if ($totalHits -gt 0) { exit 1 }
exit 0
