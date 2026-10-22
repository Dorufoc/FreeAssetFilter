#requires -Version 7.0
<#
.SYNOPSIS
  Todo 20 capture tool for the FreeAssetFilter installer (plan §14 workflow).

  Takes a real-machine screenshot of the installer window (class
  `FreeAssetFilterInstaller`) while the Todo 19 /auto drive holds it on
  page N, using a *desktop DC* BitBlt (GetDC(NULL) -> CreateCompatibleBitmap ->
  BitBlt SRCCOPY|CAPTUREBLT). PrintWindow is never used (plan §14).

  Pixel statistics gate (frozen in plan Todo 20):
    PASS  <=>  stddev(luma) > 5  AND  non-bg pixel ratio > 0.5%
  A rejected (black/blank) capture is NEVER written to -Out; it is only saved
  to -DiagDir when explicitly given for diagnosis.

.DESCRIPTION
  Modes:
    -Baseline : capture the whole virtual screen, no process/window involved.
                Proves that GetDC(NULL)+BitBlt can read the desktop at all.
    install   : launch <Exe> with /auto:page=N (+ /payload /result /installdir),
                wait for diag marker "auto stop reached page=N", optionally
                create the payload.ready sentinel after the marker, settle,
                bring the window topmost, BitBlt its rect (+PadPx ring to show
                shadow / rounded corners), gate, save PNG. Pages 0..4 only;
                this is the default and keeps the original call style.
                Page 4 (Finish) is only reachable after the install engine
                completes: auto drive does not leave Progress until the install
                thread posts WM_INSTALL_DONE, and the engine waits for
                payload.ready. For page 4 this script therefore prepares a
                minimal scratch payload (when -Payload has no files) and
                pre-creates the sentinel so the page-4 regression is
                reproducible without extra caller steps.
    maintenance : same capture pipeline, but launch with /maintenance
                /decision <ini> /installdir <scratch dir>. Before launch a
                minimal installed fixture is created at
                <installDir>\FreeAssetFilter.exe (copy of the TEST GUI) plus
                <installDir>\_internal, so page 5 does not show the
                "not installed" error. Pages 5 and 6 are supported; page 6
                additionally passes /auto:action=uninstall to navigate
                Maintenance -> UninstallConfirm.
    uninstall : launch with /uninstall /decision <ini> /installdir <dir> and
                capture the immediate UninstallConfirm page 6 (no fixture;
                page 6 is the entry page of this mode).

  -AutoArgs passes extra pre-formed test CLI tokens (for example
  '/auto:action=cancel' or '/auto:delete-user-data=1'). It may not override
  structural arguments owned by this tool (/auto:page, /auto:mode,
  /maintenance, /uninstall, /decision, /installdir, /payload, /result).

  Fixture failures and "detected=0" (not-installed error page) fail nonzero;
  a passing screenshot is never saved for those cases. The fixture lives under
  -Scratch and is removed on every exit path.

  Every mode ensures /payload is an existing directory before launch (the GUI
  paints a red startup error banner when it is missing), so captures are
  independent of prior install/page-4 scratch state. A capture also fails
  nonzero if the diag line says payload_exists=0 (or is missing), preventing
  the error banner from being saved as a passing screenshot.

  Exit codes:
    0 pass, 1 usage/env error (also invalid mode/page and fixture failure),
    2 gate failed (black/blank -> no -Out write), 3 diag requirement failed,
    4 window not found / process died early, 5 marker timeout / wrong stop
    page, 6 capture failure.

.PARAMETER Out
  Destination PNG path. Written ONLY when the gate passes.

.PARAMETER StatsFile
  Optional file to APPEND a summary + stats JSON line to (append-only).
#>
param(
    [string]$Exe = (Join-Path $PSScriptRoot '..\..\build\test-installer\FreeAssetFilterInstaller.exe'),
    [string]$Payload = '',
    [string]$Scratch = 'C:\Users\89553\AppData\Local\Temp\opencode\faf_t19',
    [ValidateSet('install', 'maintenance', 'uninstall')][string]$Mode = 'install',
    [ValidateRange(0, 7)][int]$Page = 0,
    [int]$PadPx = 24,
    [int]$MarkerTimeoutMs = 90000,
    [int]$SettleMs = 550,
    [switch]$CreateSentinel,
    [int]$SettleAfterSentinelMs = 900,
    [string]$SentinelPath = '',
    [string[]]$AutoArgs = @(),
    [string[]]$RequireDiag = @(),
    [string[]]$ForbidDiag = @(),
    [switch]$Baseline,
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$DiagDir = '',
    [string]$StatsFile = ''
)

$ErrorActionPreference = 'Stop'

try { Add-Type -AssemblyName System.Drawing } catch { Add-Type -AssemblyName System.Drawing.Common }
$drawAsm = [System.Drawing.Bitmap].Assembly.Location
$refs = @($drawAsm)
$drawHome = Split-Path $drawAsm
foreach ($n in @('System.Private.Windows.Core.dll', 'System.Private.Windows.GdiPlus.dll', 'System.Drawing.Primitives.dll')) {
    $p = Join-Path $drawHome $n
    if (Test-Path -LiteralPath $p) { $refs += $p }
}

$src = @'
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

public static class FafCap
{
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern IntPtr GetDC(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern int ReleaseDC(IntPtr hWnd, IntPtr hDC);
    [DllImport("user32.dll")] public static extern bool SetThreadDpiAwarenessContext(IntPtr ctx);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, System.Text.StringBuilder sb, int max);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleDC(IntPtr hdc);
    [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleBitmap(IntPtr hdc, int w, int h);
    [DllImport("gdi32.dll")] public static extern IntPtr SelectObject(IntPtr hdc, IntPtr obj);
    [DllImport("gdi32.dll")] public static extern bool BitBlt(IntPtr dst, int x, int y, int w, int h, IntPtr src, int sx, int sy, int rop);
    [DllImport("gdi32.dll")] public static extern bool DeleteDC(IntPtr hdc);
    [DllImport("gdi32.dll")] public static extern bool DeleteObject(IntPtr obj);

    public static void EnablePmv2() { SetThreadDpiAwarenessContext(new IntPtr(-4)); }

    public static int[] VirtualScreenArr()
    {
        return new int[] { GetSystemMetrics(76), GetSystemMetrics(77), GetSystemMetrics(78), GetSystemMetrics(79) };
    }

    public static IntPtr FindVisibleWindow(uint wantPid, string cls)
    {
        IntPtr found = IntPtr.Zero;
        EnumProc cb = delegate(IntPtr h, IntPtr lp)
        {
            if (!IsWindowVisible(h)) return true;
            var sb = new System.Text.StringBuilder(256);
            GetClassNameW(h, sb, sb.Capacity);
            if (sb.ToString() == cls)
            {
                uint pid;
                GetWindowThreadProcessId(h, out pid);
                if (wantPid == 0 || pid == wantPid) { found = h; return false; }
            }
            return true;
        };
        EnumWindows(cb, IntPtr.Zero);
        return found;
    }

    public static int[] WindowRectArr(IntPtr h)
    {
        RECT r;
        if (!GetWindowRect(h, out r)) return null;
        return new int[] { r.Left, r.Top, r.Right - r.Left, r.Bottom - r.Top };
    }

    public static Bitmap CaptureRect(int x, int y, int w, int h)
    {
        IntPtr screen = GetDC(IntPtr.Zero);
        if (screen == IntPtr.Zero) throw new Exception("GetDC(NULL) failed");
        IntPtr mem = IntPtr.Zero;
        IntPtr bmp = IntPtr.Zero;
        bool ok = false;
        try
        {
            mem = CreateCompatibleDC(screen);
            bmp = CreateCompatibleBitmap(screen, w, h);
            if (mem == IntPtr.Zero || bmp == IntPtr.Zero) throw new Exception("CreateCompatibleDC/CreateCompatibleBitmap failed");
            IntPtr old = SelectObject(mem, bmp);
            ok = BitBlt(mem, 0, 0, w, h, screen, x, y, 0x40CC0020); // SRCCOPY | CAPTUREBLT
            SelectObject(mem, old);
        }
        finally
        {
            ReleaseDC(IntPtr.Zero, screen);
        }
        if (!ok)
        {
            if (bmp != IntPtr.Zero) DeleteObject(bmp);
            if (mem != IntPtr.Zero) DeleteDC(mem);
            throw new Exception("BitBlt from desktop DC failed");
        }
        Bitmap managed;
        using (var raw = Image.FromHbitmap(bmp))
        {
            managed = new Bitmap(w, h, PixelFormat.Format32bppArgb);
            using (var g = Graphics.FromImage(managed)) { g.DrawImageUnscaled(raw, 0, 0); }
        }
        DeleteObject(bmp);
        DeleteDC(mem);
        return managed;
    }

    public static string Stats(Bitmap b)
    {
        int w = b.Width, h = b.Height;
        var rect = new Rectangle(0, 0, w, h);
        var data = b.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
        int stride = Math.Abs(data.Stride);
        byte[] buf = new byte[stride * h];
        Marshal.Copy(data.Scan0, buf, 0, buf.Length);
        b.UnlockBits(data);

        long n = (long)w * h;
        double sum = 0, sum2 = 0;
        uint[] bins = new uint[32768];
        long[] sr = new long[32768];
        long[] sg = new long[32768];
        long[] sb = new long[32768];
        int maxCh = 0;
        for (int yy = 0; yy < h; yy++)
        {
            int row = yy * stride;
            for (int xx = 0; xx < w; xx++)
            {
                int o = row + xx * 4;
                int bb = buf[o], gg = buf[o + 1], rr = buf[o + 2];
                double l = 0.299 * rr + 0.587 * gg + 0.114 * bb;
                sum += l; sum2 += l * l;
                int bi = ((rr >> 3) << 10) | ((gg >> 3) << 5) | (bb >> 3);
                bins[bi]++; sr[bi] += rr; sg[bi] += gg; sb[bi] += bb;
                if (rr > maxCh) maxCh = rr;
                if (gg > maxCh) maxCh = gg;
                if (bb > maxCh) maxCh = bb;
            }
        }
        int modal = 0; uint best = 0;
        for (int i = 0; i < bins.Length; i++) { if (bins[i] > best) { best = bins[i]; modal = i; } }
        int mr = (int)(sr[modal] / best), mg = (int)(sg[modal] / best), mb = (int)(sb[modal] / best);

        long nonbg = 0, accentBlue = 0, accentLight = 0;
        for (int yy = 0; yy < h; yy++)
        {
            int row = yy * stride;
            for (int xx = 0; xx < w; xx++)
            {
                int o = row + xx * 4;
                int bb = buf[o], gg = buf[o + 1], rr = buf[o + 2];
                if (Math.Abs(rr - mr) > 8 || Math.Abs(gg - mg) > 8 || Math.Abs(bb - mb) > 8) nonbg++;
                if (Math.Abs(rr - 0) <= 12 && Math.Abs(gg - 95) <= 12 && Math.Abs(bb - 184) <= 12) accentBlue++;
                if (Math.Abs(rr - 96) <= 12 && Math.Abs(gg - 205) <= 12 && Math.Abs(bb - 255) <= 12) accentLight++;
            }
        }
        double mean = sum / n;
        double var = sum2 / n - mean * mean;
        if (var < 0) var = 0;
        double sd = Math.Sqrt(var);
        double nr = (double)nonbg / n;
        return string.Format(System.Globalization.CultureInfo.InvariantCulture,
            "{{\"w\":{0},\"h\":{1},\"px\":{2},\"stddev\":{3:0.###},\"nonbg\":{4:0.#####},\"modal\":\"#{5:X2}{6:X2}{7:X2}\",\"maxCh\":{8},\"accentBlue\":{9},\"accentLight\":{10}}}",
            w, h, n, sd, nr, mr, mg, mb, maxCh, accentBlue, accentLight);
    }
}
'@
Add-Type -TypeDefinition $src -ReferencedAssemblies $refs

$script:child = $null
$script:installDir = ''
$script:fixtureCreated = $false
function StopChild {
    if ($script:child) {
        try {
            if (-not $script:child.HasExited) {
                Stop-Process -Id $script:child.Id -Force -ErrorAction SilentlyContinue
                $script:child.WaitForExit(5000) | Out-Null
            }
        } catch {}
    }
}
function Remove-Fixture {
    if (-not $script:fixtureCreated -or -not $script:installDir) { return }
    if (-not (Test-Path -LiteralPath $script:installDir)) {
        $script:fixtureCreated = $false
        return
    }
    # The fixture is a scratch install dir only; retry briefly so a just-killed
    # child cannot leave a locked file behind.
    for ($i = 0; $i -lt 10; $i++) {
        try {
            Remove-Item -LiteralPath $script:installDir -Recurse -Force -ErrorAction Stop
            $script:fixtureCreated = $false
            Write-Host "[FIXTURE] removed $script:installDir"
            return
        } catch {
            Start-Sleep -Milliseconds 150
        }
    }
    Write-Host "[WARN] fixture cleanup failed: $script:installDir"
}
function Cleanup {
    StopChild
    Remove-Fixture
}
function Fail([int]$code, [string]$msg) {
    Cleanup
    Write-Host "[RESULT] FAIL($code): $msg"
    exit $code
}
trap {
    $msg = $_.Exception.Message
    try { Cleanup } catch {}
    Write-Host "[RESULT] FAIL(1): unhandled error: $msg"
    exit 1
}
function Read-DiagText([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return '' }
    try {
        $fs = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try { $sr = New-Object System.IO.StreamReader $fs; return $sr.ReadToEnd() } finally { $fs.Dispose() }
    } catch { return '' }
}

[FafCap]::EnablePmv2() | Out-Null

function Invoke-GateAndSave([System.Drawing.Bitmap]$bmp, [string]$tag) {
    $stats = [FafCap]::Stats($bmp)
    Write-Host "[STATS] $stats"
    $o = $stats | ConvertFrom-Json
    $pass = ($o.stddev -gt 5.0) -and ($o.nonbg -gt 0.005)
    if ($pass) {
        $bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
        if ($StatsFile) { Add-Content -LiteralPath $StatsFile -Value ("$tag`n[STATS] $stats") -Encoding utf8 }
        Write-Host "[RESULT] PASS saved=$Out"
        Cleanup
        exit 0
    } else {
        if ($DiagDir) {
            New-Item -ItemType Directory -Force -Path $DiagDir | Out-Null
            $rej = Join-Path $DiagDir ('REJECTED-' + (Split-Path -Leaf $Out))
            $bmp.Save($rej, [System.Drawing.Imaging.ImageFormat]::Png)
            Write-Host "[DIAG] rejected capture saved to $rej"
        }
        if ($StatsFile) { Add-Content -LiteralPath $StatsFile -Value ("$tag`n[STATS] $stats`n[RESULT] GATE-FAIL") -Encoding utf8 }
        Write-Host "[RESULT] FAIL(2): gate failed (stddev=$($o.stddev) nonbg=$($o.nonbg)) - black/blank or desktop not capturable"
        Cleanup
        exit 2
    }
}

if ($Baseline) {
    $vs = [FafCap]::VirtualScreenArr()
    $tag = "[BASELINE] virtual-screen x=$($vs[0]) y=$($vs[1]) w=$($vs[2]) h=$($vs[3])"
    Write-Host $tag
    try { $bmp = [FafCap]::CaptureRect($vs[0], $vs[1], $vs[2], $vs[3]) }
    catch { Fail 6 ("baseline capture failed: " + $_.Exception.Message) }
    Invoke-GateAndSave $bmp $tag
}

if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { Fail 1 "Exe not found: $Exe" }
$exeFull = (Resolve-Path -LiteralPath $Exe).Path

# Explicit mode/page contract: never silently capture a page the mode cannot
# reach. Install keeps the original 0..4 wizard; maintenance owns 5/6;
# uninstall starts on the confirmation page 6.
$pageRanges = @{ install = @(0, 4); maintenance = @(5, 6); uninstall = @(6, 6) }
$lo = $pageRanges[$Mode][0]
$hi = $pageRanges[$Mode][1]
if ($Page -lt $lo -or $Page -gt $hi) {
    Fail 1 ("unsupported -Mode/-Page combination: Mode=$Mode Page=$Page " +
            "(supported $lo..$hi). install=0..4, maintenance=5/6, uninstall=6.")
}
foreach ($a in $AutoArgs) {
    if ([string]::IsNullOrWhiteSpace($a)) { Fail 1 "-AutoArgs contains an empty token" }
    if (-not $a.StartsWith('/')) { Fail 1 "-AutoArgs token must start with '/': $a" }
    foreach ($reserved in @('/auto:page=', '/auto:mode=', '/maintenance', '/uninstall',
                            '/installdir', '/decision', '/payload', '/result')) {
        if ($a.StartsWith($reserved, [StringComparison]::OrdinalIgnoreCase)) {
            Fail 1 "-AutoArgs may not override the tool-owned argument '$reserved': $a"
        }
    }
}

if (-not $Payload) { $Payload = Join-Path $Scratch 'payload' }
if (-not $SentinelPath) { $SentinelPath = Join-Path $Scratch 'payload.ready' }
try { New-Item -ItemType Directory -Force -Path $Scratch | Out-Null }
catch { Fail 1 ("cannot create scratch directory '$Scratch': " + $_.Exception.Message) }

$diag = Join-Path $Scratch "page-$Mode-$Page.diag.log"
$result = Join-Path $Scratch "page-$Mode-$Page-result.ini"
$decision = Join-Path $Scratch "maintenance-decision-$Mode-$Page.ini"
$installDir = Join-Path $Scratch "install-$Mode-page-$Page"
$scratchFull = [System.IO.Path]::GetFullPath($Scratch).TrimEnd('\')
$installFull = [System.IO.Path]::GetFullPath($installDir)
if (-not $installFull.StartsWith($scratchFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
    Fail 1 "refusing install dir outside -Scratch: $installFull"
}
foreach ($forbidden in @((Join-Path $env:LOCALAPPDATA 'FreeAssetFilter'),
                         (Join-Path $env:LOCALAPPDATA 'FreeAssetFilterTest'))) {
    $forbiddenFull = [System.IO.Path]::GetFullPath($forbidden).TrimEnd('\')
    if ([string]::Equals($installFull.TrimEnd('\'), $forbiddenFull, [StringComparison]::OrdinalIgnoreCase)) {
        Fail 1 "refusing production/test install directory: $installFull"
    }
}

if ($Mode -eq 'maintenance') {
    # The fixture must be built from the test GUI, never the production one.
    if ($exeFull -match '\\build\\installer\\') {
        Fail 1 "refusing to build the maintenance fixture from the production GUI: $exeFull (use the FAF_TESTMODE build under build/test-installer)"
    }
}

Remove-Item -LiteralPath $diag, $result, $decision, $SentinelPath -Force -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $installDir) {
    Remove-Item -LiteralPath $installDir -Recurse -Force -ErrorAction SilentlyContinue
}

# The GUI sets its startup error banner whenever /payload does not exist, even
# in maintenance/uninstall modes. Every capture must therefore be independent
# of prior install/page-4 scratch state: ensure /payload is an existing
# directory before launch (empty is fine for non-install modes).
if (Test-Path -LiteralPath $Payload -PathType Leaf) {
    Fail 1 "payload path is a file, not a directory: $Payload"
}
if (-not (Test-Path -LiteralPath $Payload -PathType Container)) {
    try {
        New-Item -ItemType Directory -Force -Path $Payload -ErrorAction Stop | Out-Null
        Write-Host "[PAYLOAD] created empty payload directory $Payload"
    } catch {
        Fail 1 ("cannot create payload directory '$Payload': " + $_.Exception.Message)
    }
}

# Minimal installed fixture for maintenance mode (D15 H1 detection = exe or
# _internal). Page 5 would otherwise render the not-installed error page.
if ($Mode -eq 'maintenance') {
    $script:installDir = $installDir
    try {
        New-Item -ItemType Directory -Force -Path $installDir -ErrorAction Stop | Out-Null
        $fixtureExe = Join-Path $installDir 'FreeAssetFilter.exe'
        $fixtureInternal = Join-Path $installDir '_internal'
        Copy-Item -LiteralPath $exeFull -Destination $fixtureExe -Force -ErrorAction Stop
        New-Item -ItemType Directory -Force -Path $fixtureInternal -ErrorAction Stop | Out-Null
        if (-not (Test-Path -LiteralPath $fixtureExe -PathType Leaf)) { throw "fixture exe missing after copy" }
        if (-not (Test-Path -LiteralPath $fixtureInternal -PathType Container)) { throw "fixture _internal missing after create" }
        $script:fixtureCreated = $true
        Write-Host "[FIXTURE] created $installDir (FreeAssetFilter.exe=$((Get-Item -LiteralPath $fixtureExe).Length) bytes, _internal=dir)"
    } catch {
        # Mark the partial fixture for cleanup even if it was only half-made.
        $script:fixtureCreated = $true
        Fail 1 ("maintenance fixture creation failed under '$installDir': " + $_.Exception.Message)
    }
}

# Page 4 (Finish) is only reachable after the install engine completes. Auto
# drive deliberately does not advance off Progress, and the engine blocks on
# payload.ready. Prepare a minimal scratch payload (when the caller did not
# supply one) and pre-create the sentinel so page 4 remains reproducible with
# the default install call style.
$sentinelPrecreated = $false
if ($Mode -eq 'install' -and $Page -eq 4) {
    try {
        New-Item -ItemType Directory -Force -Path $Payload -ErrorAction Stop | Out-Null
        $firstPayloadFile = Get-ChildItem -LiteralPath $Payload -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $firstPayloadFile) {
            $probe = Join-Path $Payload '_internal\capture-probe.txt'
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $probe) -ErrorAction Stop | Out-Null
            Set-Content -LiteralPath $probe -Value 'page 4 capture probe' -Encoding utf8 -ErrorAction Stop
            Write-Host "[PAYLOAD] page 4 minimal payload prepared: $probe"
        } else {
            Write-Host "[PAYLOAD] page 4 using existing payload files under $Payload"
        }
        Remove-Item -LiteralPath $SentinelPath -Force -ErrorAction SilentlyContinue
        New-Item -ItemType File -Force -Path $SentinelPath -ErrorAction Stop | Out-Null
        $sentinelPrecreated = $true
        Write-Host "[SENTINEL] pre-created $SentinelPath so the install can reach page 4"
    } catch {
        Fail 1 ("page 4 payload/sentinel preparation failed: " + $_.Exception.Message)
    }
}

$argParts = New-Object System.Collections.Generic.List[string]
switch ($Mode) {
    'maintenance' {
        $argParts.Add('/maintenance')
        $argParts.Add("/decision `"$decision`"")
    }
    'uninstall' {
        $argParts.Add('/uninstall')
        $argParts.Add("/decision `"$decision`"")
    }
}
$argParts.Add("/payload `"$Payload`"")
$argParts.Add("/result `"$result`"")
$argParts.Add("/installdir `"$installDir`"")
$argParts.Add("/auto:page=$Page")

$autoAction = $null
foreach ($a in $AutoArgs) {
    if ($a -match '^/auto:action=(.+)$') { $autoAction = $matches[1] }
}
if ($Mode -eq 'maintenance' -and $Page -eq 6) {
    # The only automatic path from Maintenance (5) to UninstallConfirm (6).
    if ($null -ne $autoAction -and $autoAction -notmatch '^uninstall$') {
        Fail 1 "maintenance page 6 requires /auto:action=uninstall; got '$autoAction'"
    }
    if ($null -eq $autoAction) { $argParts.Add('/auto:action=uninstall') }
}
foreach ($a in $AutoArgs) {
    if ($a -match '\s') { $argParts.Add('"' + $a + '"') } else { $argParts.Add($a) }
}
$arg = $argParts -join ' '

Write-Host "[LAUNCH] mode=$Mode page=$Page exe=$Exe"
Write-Host "[LAUNCH] args=$arg (diag=$diag)"
$env:FAF_DIAG_PATH = $diag
$env:FAF_PAYLOAD_TIMEOUT_MS = '120000'
try {
    $script:child = Start-Process -FilePath $Exe -ArgumentList $arg -WorkingDirectory $Scratch -PassThru -ErrorAction Stop
} catch {
    Remove-Item Env:\FAF_DIAG_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:\FAF_PAYLOAD_TIMEOUT_MS -ErrorAction SilentlyContinue
    Fail 1 ("failed to start installer: " + $_.Exception.Message)
}
Remove-Item Env:\FAF_DIAG_PATH -ErrorAction SilentlyContinue
Remove-Item Env:\FAF_PAYLOAD_TIMEOUT_MS -ErrorAction SilentlyContinue

$marker = "auto stop reached page=$Page"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$found = $false
$stoppedPage = -1
while ($sw.ElapsedMilliseconds -lt $MarkerTimeoutMs) {
    if ($script:child.HasExited) { Fail 4 "process exited early (code=$($script:child.ExitCode)) before marker" }
    $txt = Read-DiagText $diag
    if ($txt -match [regex]::Escape($marker)) { $found = $true; break }
    # Fail fast instead of waiting out the timeout: the not-installed error
    # path shows Message (7) and logs detected=0.
    if ($Mode -eq 'maintenance' -and $txt -match 'maintenance detect .*detected=0') {
        Fail 1 "maintenance fixture was not detected (diag detected=0): page 5 would show the not-installed error, refusing to save a passing screenshot (diag=$diag)"
    }
    $other = [regex]::Match($txt, 'auto stop reached page=(\d+)')
    if ($other.Success) {
        $stoppedPage = [int]$other.Groups[1].Value
        break
    }
    Start-Sleep -Milliseconds 100
}
if (-not $found) {
    if ($stoppedPage -ge 0) {
        Fail 5 "auto drive stopped at page=$stoppedPage, expected page=$Page (mode=$Mode); wrong page / not-installed error / missing action (diag=$diag)"
    }
    Fail 5 "marker timeout after ${MarkerTimeoutMs}ms: '$marker' (diag=$diag)"
}
Write-Host "[MARKER] '$marker' seen after $($sw.ElapsedMilliseconds)ms"


if ($CreateSentinel -and -not $sentinelPrecreated) {
    Remove-Item -LiteralPath $SentinelPath -Force -ErrorAction SilentlyContinue
    New-Item -ItemType File -Force -Path $SentinelPath | Out-Null
    Write-Host "[SENTINEL] created $SentinelPath"
    Start-Sleep -Milliseconds $SettleAfterSentinelMs
} elseif ($sentinelPrecreated) {
    # Installation already completed while waiting for the page-4 marker;
    # give the Finish page entry animation time to settle.
    Start-Sleep -Milliseconds $SettleAfterSentinelMs
} else {
    Start-Sleep -Milliseconds $SettleMs
}

$txt = Read-DiagText $diag
if ($txt -notmatch '(?m)^payload_exists=1\s*$') {
    $payloadDetail = if ($txt -match '(?m)^payload_exists=0\s*$') { 'payload_exists=0' } else { 'payload_exists line missing' }
    Fail 1 "payload directory check failed ($payloadDetail): $Payload; refusing to save a screenshot that may contain the error banner (diag=$diag)"
}
if ($Mode -eq 'maintenance' -and $txt -notmatch 'maintenance detect .*detected=1') {
    Fail 1 "maintenance mode did not log detected=1 for the scratch fixture; page 5 is not a valid maintenance page (diag=$diag)"
}
foreach ($pat in $RequireDiag) { if ($txt -notmatch $pat) { Fail 3 "required diag pattern missing: '$pat'" } }
foreach ($pat in $ForbidDiag) { if ($txt -match $pat) { Fail 3 "forbidden diag pattern present: '$pat'" } }

$hwnd = [IntPtr]::Zero
$sw2 = [System.Diagnostics.Stopwatch]::StartNew()
while ($sw2.ElapsedMilliseconds -lt 5000) {
    $hwnd = [FafCap]::FindVisibleWindow([uint32]$script:child.Id, 'FreeAssetFilterInstaller')
    if ($hwnd -ne [IntPtr]::Zero) { break }
    Start-Sleep -Milliseconds 100
}
if ($hwnd -eq [IntPtr]::Zero) { Fail 4 "window class FreeAssetFilterInstaller not found (visible) for pid $($script:child.Id)" }

[FafCap]::SetWindowPos($hwnd, [IntPtr](-1), 0, 0, 0, 0, 0x13) | Out-Null  # HWND_TOPMOST, NOSIZE|NOMOVE|NOACTIVATE
[FafCap]::SetForegroundWindow($hwnd) | Out-Null
Start-Sleep -Milliseconds 150

$r = [FafCap]::WindowRectArr($hwnd)
if (-not $r) { Fail 6 "GetWindowRect failed" }
$vs = [FafCap]::VirtualScreenArr()
$vx = $vs[0]; $vy = $vs[1]; $vw = $vs[2]; $vh = $vs[3]
$x = $r[0] - $PadPx; $y = $r[1] - $PadPx; $w = $r[2] + 2 * $PadPx; $h = $r[3] + 2 * $PadPx
$clamped = $false
if ($x -lt $vx) { $w -= ($vx - $x); $x = $vx; $clamped = $true }
if ($y -lt $vy) { $h -= ($vy - $y); $y = $vy; $clamped = $true }
if (($x + $w) -gt ($vx + $vw)) { $w = ($vx + $vw) - $x; $clamped = $true }
if (($y + $h) -gt ($vy + $vh)) { $h = ($vy + $vh) - $y; $clamped = $true }
$tag = "[WINDOW] mode=$Mode page=$Page pid=$($script:child.Id) hwnd=0x$('{0:X}' -f [int64]$hwnd) rect=$($r[0]),$($r[1]),$($r[2]),$($r[3]) capture=$x,$y,$w,$h pad=$PadPx clamped=$clamped"
Write-Host $tag

try { $bmp = [FafCap]::CaptureRect($x, $y, $w, $h) }
catch { Fail 6 ("capture failed: " + $_.Exception.Message) }

[FafCap]::SetWindowPos($hwnd, [IntPtr](-2), 0, 0, 0, 0, 0x13) | Out-Null  # HWND_NOTOPMOST
Invoke-GateAndSave $bmp $tag
