@echo off
REM =============================================================================
REM Thumbnail Generator Build Script for Windows CMD
REM =============================================================================
REM 
REM This script builds the thumbnail generator using CMake and either MinGW-w64 or
REM Visual Studio. It automatically detects the available build environment.
REM 
REM Usage:
REM   build.bat [clean] [debug|release]
REM 
REM Options:
REM   clean    - Clean the build directory before building
REM   debug    - Build in Debug mode (default: Release)
REM   release  - Build in Release mode
REM 
REM =============================================================================

setlocal EnableDelayedExpansion

REM -----------------------------------------------------------------------------
REM Configuration
REM -----------------------------------------------------------------------------
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%"
set "BUILD_DIR=%PROJECT_ROOT%build"

REM Default build type
set "BUILD_TYPE=Release"
set "CLEAN_BUILD=0"

REM -----------------------------------------------------------------------------
REM Parse command line arguments
REM -----------------------------------------------------------------------------
for %%i in (%*) do (
    if /i "%%i"=="clean" set "CLEAN_BUILD=1"
    if /i "%%i"=="debug" set "BUILD_TYPE=Debug"
    if /i "%%i"=="release" set "BUILD_TYPE=Release"
)

REM -----------------------------------------------------------------------------
REM Display script information
REM -----------------------------------------------------------------------------
echo =============================================================================
echo Thumbnail Generator Build Script for Windows CMD
echo =============================================================================
echo Build Type: %BUILD_TYPE%
echo Clean Build: %CLEAN_BUILD%
echo Project Root: %PROJECT_ROOT%
echo Build Directory: %BUILD_DIR%
echo =============================================================================
echo.

REM -----------------------------------------------------------------------------
REM Check for required tools
REM -----------------------------------------------------------------------------
echo Checking required tools...

REM Check CMake
where cmake >nul 2>&1
if errorlevel 1 (
    echo ERROR: CMake is not installed. Please install CMake first.
    echo Download from: https://cmake.org/download/
    pause
    exit /b 1
)

echo ✓ CMake is installed.
echo.

REM -----------------------------------------------------------------------------
REM Clean build directory if requested
REM -----------------------------------------------------------------------------
if %CLEAN_BUILD% equ 1 (
    echo Cleaning build directory...
    if exist "%BUILD_DIR%" (
        rmdir /s /q "%BUILD_DIR%" >nul 2>&1
    )
    echo ✓ Build directory cleaned.
echo.
)

REM -----------------------------------------------------------------------------
REM Create build directory
REM -----------------------------------------------------------------------------
if not exist "%BUILD_DIR%" (
    mkdir "%BUILD_DIR%" >nul 2>&1
    echo Created build directory: %BUILD_DIR%
)

REM -----------------------------------------------------------------------------
REM Detect build environment
REM -----------------------------------------------------------------------------
echo Detecting build environment...

set "MINGW_FOUND=0"
set "VS_FOUND=0"

REM Check for MinGW-w64
tasklist | find /i "gcc.exe" >nul 2>&1
if not errorlevel 1 set "MINGW_FOUND=1"

if %MINGW_FOUND% equ 0 (
    where gcc >nul 2>&1
    if not errorlevel 1 set "MINGW_FOUND=1"
)

if %MINGW_FOUND% equ 1 (
    echo ✓ Found MinGW-w64 environment.
) else (
    echo Checking for Visual Studio...
    if defined VSINSTALLDIR (
        set "VS_FOUND=1"
        echo ✓ Using existing Visual Studio environment.
    ) else (
        echo ⚠ Visual Studio environment not found.
        echo   Looking for Visual Studio 2022...
        
        if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" (
            set "VS_FOUND=1"
            echo ✓ Found Visual Studio 2022 Build Tools.
        ) else if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" (
            set "VS_FOUND=1"
            echo ✓ Found Visual Studio 2022 Community.
        ) else if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat" (
            set "VS_FOUND=1"
            echo ✓ Found Visual Studio 2022 Professional.
        )
    )
)

REM -----------------------------------------------------------------------------
REM Ensure we have a valid build environment
REM -----------------------------------------------------------------------------
if %MINGW_FOUND% equ 0 if %VS_FOUND% equ 0 (
    echo.
    echo ERROR: No C++ compiler found.
    echo Please install one of the following:
    echo   - MinGW-w64: https://www.mingw-w64.org/downloads/
    echo   - Visual Studio: https://visualstudio.microsoft.com/downloads/
    echo.
    pause
    exit /b 1
)

echo.

REM -----------------------------------------------------------------------------
REM Run CMake configuration
REM -----------------------------------------------------------------------------
echo Running CMake configuration...
echo -----------------------------------------------------------------------------

cd /d "%BUILD_DIR%" >nul 2>&1

if %MINGW_FOUND% equ 1 (
    REM Use MinGW-w64
    cmake -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=%BUILD_TYPE% ..
) else (
    REM Use Visual Studio
    cmake -G "Ninja" -DCMAKE_BUILD_TYPE=%BUILD_TYPE% ..
    if errorlevel 1 (
        echo.
        echo ⚠ Ninja generator failed, trying Visual Studio generator...
        cmake -G "Visual Studio 17 2022" -A x64 ..
    )
)

if errorlevel 1 (
    echo.
    echo ERROR: CMake configuration failed.
    pause
    exit /b 1
)

echo ✓ CMake configuration completed successfully.
echo.

REM -----------------------------------------------------------------------------
REM Build the project
REM -----------------------------------------------------------------------------
echo Building the project...
echo -----------------------------------------------------------------------------

if %MINGW_FOUND% equ 1 (
    REM Build with MinGW-w64
    if exist "%ProgramFiles%\Git\usr\bin\which.exe" (
        set "WHICH=which"
    ) else (
        set "WHICH=where"
    )
    
    %WHICH% mingw32-make >nul 2>&1
    if not errorlevel 1 (
        mingw32-make -j%NUMBER_OF_PROCESSORS%
    ) else (
        make -j%NUMBER_OF_PROCESSORS%
    )
) else (
    REM Build with Visual Studio
    if exist "build.ninja" (
        ninja
    ) else (
        cmake --build . --config %BUILD_TYPE%
    )
)

if errorlevel 1 (
    echo.
    echo ERROR: Build failed.
    pause
    exit /b 1
)

echo.
echo =============================================================================
echo ✓ Build completed successfully!
echo =============================================================================

REM -----------------------------------------------------------------------------
REM Locate and display the executable path
REM -----------------------------------------------------------------------------
set "EXECUTABLE=%BUILD_DIR%\thumbnail_generator.exe"
if %MINGW_FOUND% equ 0 (
    set "EXECUTABLE=%BUILD_DIR%\%BUILD_TYPE%\thumbnail_generator.exe"
)

if exist "%EXECUTABLE%" (
    echo.
    echo Executable: %EXECUTABLE%
echo.
    echo You can now run the thumbnail generator:
echo   %EXECUTABLE% --help
) else (
    echo.
    echo ⚠ Executable not found at expected location.
    echo Please check the build output for the actual location.
)

echo.
pause
endlocal
