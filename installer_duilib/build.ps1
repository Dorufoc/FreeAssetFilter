$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$build = Join-Path $root 'build'
$cmake = 'C:\Program Files\CMake\bin\cmake.exe'
$mingw = 'C:\msys64\mingw64\bin'
$env:Path = "$mingw;$env:Path"
$nsis = 'C:\Program Files (x86)\NSIS\makensis.exe'
if (Test-Path (Join-Path $build 'CMakeCache.txt')) { Remove-Item -LiteralPath $build -Recurse -Force }
New-Item -ItemType Directory -Force -Path $build | Out-Null
& $cmake -S $root -B $build -G 'MinGW Makefiles' -DCMAKE_CXX_COMPILER="$($mingw.Replace('\','/'))/g++.exe" -DCMAKE_RC_COMPILER="$($mingw.Replace('\','/'))/windres.exe"
if ($LASTEXITCODE -ne 0) { throw 'CMake configure failed' }
& $cmake --build $build --config Release
if ($LASTEXITCODE -ne 0) { throw 'CMake build failed' }
$objdump = Join-Path $mingw 'objdump.exe'
$deps = (& $objdump -p (Join-Path $build 'FreeAssetFilterInstaller.exe') | Select-String 'DLL Name') -join "`n"
if ($deps -match 'libgcc_s_seh-1|libstdc\+\+-6') { throw "Bootstrapper still depends on MSYS2 runtime:`n$deps" }
$installerOut = Join-Path $root '..\build\installer\FreeAssetFilterInstaller.exe'
$runtimeDll = Join-Path $mingw 'libwinpthread-1.dll'
if (-not (Test-Path $runtimeDll)) { throw "Missing MinGW runtime: $runtimeDll" }
New-Item -ItemType Directory -Force -Path (Split-Path $installerOut) | Out-Null
Copy-Item (Join-Path $build 'FreeAssetFilterInstaller.exe') $installerOut -Force
Copy-Item $runtimeDll (Join-Path (Split-Path $installerOut) 'libwinpthread-1.dll') -Force
& $nsis (Join-Path $root 'installer.nsi')
if ($LASTEXITCODE -ne 0) { throw 'NSIS build failed' }
Write-Host "Built: $installerOut"
