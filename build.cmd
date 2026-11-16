@echo off
setlocal EnableExtensions

title Sopeek Release Build
chcp 65001 >nul 2>&1

cd /d "%~dp0"
if not exist "%~dp0tools\build_double_click.ps1" (
    echo [ERROR] Missing tools\build_double_click.ps1
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

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "SPK_BUILD_NO_PAUSE=1"

echo Using PowerShell: %SPK_PS%
echo Repository       : %~dp0
echo.

"%SPK_PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build_double_click.ps1" %*
set "SPK_EXIT=%ERRORLEVEL%"

echo.
if "%SPK_EXIT%"=="0" (
    echo Build finished successfully.
) else (
    echo Build failed with exit code %SPK_EXIT%.
)
echo Press any key to close this window...
pause >nul

exit /b %SPK_EXIT%
