param([string]$Compiler = 'g++')
$ErrorActionPreference = 'Stop'
$src = Join-Path $PSScriptRoot '../src'
$files = 'controls_basic','license_sheet','animation','controls_feedback','text','glyphs','layout','theme' | ForEach-Object { Join-Path $src "render/$_.cpp" }
$exe = Join-Path ([IO.Path]::GetTempPath()) ('spk-input-' + [guid]::NewGuid() + '.exe')
try {
    & $Compiler -std=c++17 -DWINVER=0x0A00 -D_WIN32_WINNT=0x0A00 -DNOMINMAX -DUNICODE -D_UNICODE -I $src (Join-Path $PSScriptRoot 'input_interaction.cpp') $files -static -ld2d1 -ldwrite -ldwmapi -ld3d11 -o $exe
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $exe
    exit $LASTEXITCODE
} finally {
    if (Test-Path -LiteralPath $exe) { Remove-Item -LiteralPath $exe }
}
