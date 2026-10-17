$ErrorActionPreference = 'Stop'
# Todo 19 (contract §17): build the FAF_TESTMODE test GUI with the unattended
# /auto drive compiled in (cmake/test_mode.cmake -> FAF_TESTMODE define).
# Output: <repo-root>\build\test-installer\FreeAssetFilterInstaller.exe (plus
# libwinpthread-1.dll for direct runs). This script NEVER touches the production
# chain (installer_duilib\build, build\installer\..., build\FreeAssetFilter_NSIS_Setup.exe).
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)  # installer_duilib
$build = Join-Path $root 'build\test-gui'
$cmake = 'C:\Program Files\CMake\bin\cmake.exe'
$mingw = 'C:\msys64\mingw64\bin'
$env:Path = "$mingw;$env:Path"
if (Test-Path (Join-Path $build 'CMakeCache.txt')) { Remove-Item -LiteralPath $build -Recurse -Force }
New-Item -ItemType Directory -Force -Path $build | Out-Null
& $cmake -S $root -B $build -G 'MinGW Makefiles' -DCMAKE_CXX_COMPILER="$($mingw.Replace('\','/'))/g++.exe" -DCMAKE_RC_COMPILER="$($mingw.Replace('\','/'))/windres.exe" -DFAF_TESTMODE=ON
if ($LASTEXITCODE -ne 0) { throw 'CMake configure failed' }
& $cmake --build $build --config Release
if ($LASTEXITCODE -ne 0) { throw 'CMake build failed' }
$objdump = Join-Path $mingw 'objdump.exe'
$deps = (& $objdump -p (Join-Path $build 'FreeAssetFilterInstaller.exe') | Select-String 'DLL Name') -join "`n"
if ($deps -match 'libgcc_s_seh-1|libstdc\+\+-6') { throw "Test bootstrapper still depends on MSYS2 runtime:`n$deps" }
$installerOut = Join-Path $root '..\build\test-installer\FreeAssetFilterInstaller.exe'
$runtimeDll = Join-Path $mingw 'libwinpthread-1.dll'
if (-not (Test-Path $runtimeDll)) { throw "Missing MinGW runtime: $runtimeDll" }
New-Item -ItemType Directory -Force -Path (Split-Path $installerOut) | Out-Null
Copy-Item (Join-Path $build 'FreeAssetFilterInstaller.exe') $installerOut -Force
Copy-Item $runtimeDll (Join-Path (Split-Path $installerOut) 'libwinpthread-1.dll') -Force
Write-Host "Built test GUI: $installerOut"
