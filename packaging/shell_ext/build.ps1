# 构建 SopeekShellExt.dll（资源管理器右键菜单 COM 扩展）。
#
# 用法（仓库根目录或任意位置）：
#   powershell -ExecutionPolicy Bypass -File packaging/shell_ext/build.ps1
#   powershell -ExecutionPolicy Bypass -File packaging/shell_ext/build.ps1 -Destination build/pyinstall/Sopeek
#
# 设计：本脚本不依赖安装器构建；packaging/installer/build.ps1 会在打包前调用它，
# 把 DLL 直接放进 payload 目录，随安装包一起落地到 $INSTDIR。
param(
    [string]$CMake,
    [string]$MinGWBin,
    [string]$Destination,
    [string]$BuildDir
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent (Split-Path -Parent $root)

# 默认构建目录放在仓库根 build/ 下（该目录已被 .gitignore 排除），避免手工
# 直接运行脚本时在源码目录里留下 in-source 的 CMake 产物。
if (-not $BuildDir) { $BuildDir = Join-Path $repoRoot 'build\shell_ext' }
if (-not $Destination) { $Destination = Join-Path $repoRoot 'build\installer' }

# 仓库路径含非 ASCII 时 CMake + MinGW 会以 ANSI 解读路径而失败（安装器构建
# 脚本有同样的保护）。这里直接给出明确失败，避免半途而废的构建产物。
if ($repoRoot -match '[^\x00-\x7F]') {
    throw "仓库路径包含非 ASCII 字符，CMake + MinGW 无法可靠构建：$repoRoot"
}

function Resolve-Tool {
    param([string]$Override, [string]$Preferred, [string]$CommandName, [string]$Label)
    if ($Override -and (Test-Path -LiteralPath $Override)) {
        return (Resolve-Path -LiteralPath $Override).ProviderPath
    }
    if ($Preferred -and (Test-Path -LiteralPath $Preferred)) { return $Preferred }
    $found = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    throw "Cannot locate ${Label}: '$Preferred' does not exist and '$CommandName' is not on PATH. Set SPK_CMAKE / SPK_MINGW_BIN."
}

if (-not $CMake) {
    $CMake = Resolve-Tool -Override $env:SPK_CMAKE -Preferred 'C:\Program Files\CMake\bin\cmake.exe' `
        -CommandName 'cmake' -Label 'CMake'
}

if (-not $MinGWBin) {
    $MinGWBin = $env:SPK_MINGW_BIN
    if (-not $MinGWBin -or -not (Test-Path -LiteralPath (Join-Path $MinGWBin 'g++.exe'))) {
        $MinGWBin = 'C:\msys64\mingw64\bin'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $MinGWBin 'g++.exe'))) {
        $gxx = Get-Command 'g++.exe' -ErrorAction SilentlyContinue
        if (-not $gxx) { throw "Cannot locate MinGW g++ (checked SPK_MINGW_BIN, $MinGWBin and PATH)." }
        $MinGWBin = Split-Path -Parent $gxx.Source
    }
}
$MinGWBin = (Resolve-Path -LiteralPath $MinGWBin).ProviderPath
$env:Path = "$MinGWBin;$env:Path"

Write-Host "shell_ext cmake : $CMake"
Write-Host "shell_ext mingw : $MinGWBin"

if (Test-Path (Join-Path $BuildDir 'CMakeCache.txt')) {
    Remove-Item -LiteralPath $BuildDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

$mingwSlashed = $MinGWBin.Replace('\', '/')
& $CMake -S $root -B $BuildDir -G 'MinGW Makefiles' `
    "-DCMAKE_CXX_COMPILER=$mingwSlashed/g++.exe" `
    "-DCMAKE_RC_COMPILER=$mingwSlashed/windres.exe"
if ($LASTEXITCODE -ne 0) { throw 'SopeekShellExt CMake configure failed' }

& $CMake --build $BuildDir --config Release
if ($LASTEXITCODE -ne 0) { throw 'SopeekShellExt CMake build failed' }

$dll = Join-Path $BuildDir 'SopeekShellExt.dll'
if (-not (Test-Path -LiteralPath $dll)) { throw "CMake did not produce the shell extension: $dll" }

# 与安装器一致：断言没有 MSYS2 运行时依赖（否则目标机静默加载失败）。
$objdump = Join-Path $MinGWBin 'objdump.exe'
if (Test-Path -LiteralPath $objdump) {
    $deps = (& $objdump -p $dll | Select-String 'DLL Name') -join "`n"
    if ($deps -match 'libgcc_s_seh-1|libstdc\+\+-6|libwinpthread') {
        throw "SopeekShellExt still depends on MSYS2 runtime:`n$deps"
    }
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$target = Join-Path $Destination 'SopeekShellExt.dll'
Copy-Item -LiteralPath $dll -Destination $target -Force
$size = (Get-Item -LiteralPath $target).Length
if ($size -le 0) { throw "Copied shell extension is empty: $target" }

Write-Host "Built shell ext: $target ($size bytes)"
