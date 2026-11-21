# Compile the isolated page regression executable. No installer or NSIS targets.
param([string]$Compiler = 'C:\msys64\mingw64\bin\g++.exe')
$ErrorActionPreference = 'Stop'
$src = Join-Path $PSScriptRoot '../../packaging/installer/src'
$units = 'pages_maintenance','pages_progress','pages_welcome','hero_art','controls_basic','controls_feedback','layout','theme','text','glyphs','animation' | ForEach-Object { Join-Path $src "render/$_.cpp" }
$out = Join-Path $env:TEMP ('installer-maint-' + [guid]::NewGuid() + '.exe')
$oldPath = $env:Path
try {
    $env:Path = "$(Split-Path (Get-Command $Compiler).Source);$env:Path"
    & $Compiler -std=c++17 -DUNICODE -D_UNICODE -DNOMINMAX -DWINVER=0x0A00 -D_WIN32_WINNT=0x0A00 "-I$src" "$PSScriptRoot/installer_maintenance_pages.cpp" $units -ld3d11 -ldwrite -ld2d1 -lgdi32 -ldwmapi -lole32 -o $out
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    & $out
    exit $LASTEXITCODE
} finally {
    $env:Path = $oldPath
    if ((Test-Path -LiteralPath $out) -and (Resolve-Path -LiteralPath $out).Path -eq $out) { Remove-Item -LiteralPath $out }
}
