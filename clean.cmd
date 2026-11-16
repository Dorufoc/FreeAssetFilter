@echo off
setlocal EnableExtensions

title Sopeek Clean Build Artifacts
chcp 65001 >nul 2>&1

cd /d "%~dp0"
if not exist "%~dp0tools\clean_build.ps1" (
    echo [ERROR] Missing tools\clean_build.ps1
    echo         Please make sure the repository is complete.
    pause
    exit /b 2
)

set "SPK_PS=pwsh.exe"
where pwsh.exe >nul 2>&1
if errorlevel 1 set "SPK_PS=powershell.exe"

where %SPK_PS% >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Neither pwsh.exe nor powershell.exe was found in PATH.
    pause
    exit /b 2
)

echo Using PowerShell: %SPK_PS%
echo Repository       : %~dp0
echo.

"%SPK_PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\clean_build.ps1" %*
set "SPK_EXIT=%ERRORLEVEL%"

echo.
if "%SPK_EXIT%"=="0" (
    echo Clean finished successfully.
) else (
    echo Clean finished with exit code %SPK_EXIT%.
)

if "%SPK_CLEAN_NO_PAUSE%"=="1" exit /b %SPK_EXIT%
echo Press any key to close this window...
pause >nul

exit /b %SPK_EXIT%
