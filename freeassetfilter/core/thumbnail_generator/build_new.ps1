<#
.SYNOPSIS
Thumbnail Generator Build Script for PowerShell

.DESCRIPTION
This script builds the thumbnail generator using CMake and either MinGW-w64 or Visual Studio.

.EXAMPLE
./build_new.ps1

This will build the thumbnail generator using the default settings.
#>

Write-Host "=== Thumbnail Generator Build Script ===" -ForegroundColor Green
Write-Host

# Check if CMake is installed
if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    Write-Host "Error: CMake is not installed. Please install CMake first." -ForegroundColor Red
    Write-Host "Download from: https://cmake.org/download/"
    Read-Host -Prompt "Press Enter to exit"
    exit 1
}

Write-Host "CMake is installed." -ForegroundColor Green
Write-Host

# Set build directory
$BUILD_DIR = Join-Path -Path $PSScriptRoot -ChildPath "build"
New-Item -ItemType Directory -Path $BUILD_DIR -Force | Out-Null

# Change to build directory
Set-Location -Path $BUILD_DIR

# Check if MinGW-w64 is available
$MINGW_FOUND = $false
if (Get-Command gcc -ErrorAction SilentlyContinue) {
    $gccVersion = gcc --version
    if ($gccVersion -match "mingw-w64") {
        $MINGW_FOUND = $true
        Write-Host "Found MinGW-w64 environment" -ForegroundColor Yellow
    }
}

# If no MinGW-w64, try to detect Visual Studio
$USE_VS = $false
if (-not $MINGW_FOUND) {
    if ($env:VSINSTALLDIR) {
        Write-Host "Using existing Visual Studio environment" -ForegroundColor Yellow
        $USE_VS = $true
    } else {
        Write-Host "Looking for Visual Studio..." -ForegroundColor Yellow
        
        # Try to find Visual Studio 2022
        $vsPaths = @(
            "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
            "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat",
            "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"
        )
        
        $vcvarsPath = $null
        foreach ($path in $vsPaths) {
            if (Test-Path $path) {
                $vcvarsPath = $path
                break
            }
        }
        
        if ($vcvarsPath) {
            Write-Host "Found Visual Studio 2022" -ForegroundColor Yellow
            # Run vcvars64.bat to set up the environment
            & cmd /c "$vcvarsPath && powershell.exe -NoExit -Command 'Set-Location -Path \"$BUILD_DIR\"; .\build.ps1'"
            exit 0
        } else {
            Write-Host "Error: No C++ compiler found. Please install MinGW-w64 or Visual Studio with C++ support." -ForegroundColor Red
            Write-Host "MinGW-w64 download: https://www.mingw-w64.org/downloads/"
            Write-Host "Visual Studio download: https://visualstudio.microsoft.com/downloads/"
            Read-Host -Prompt "Press Enter to exit"
            exit 1
        }
    }
}

Write-Host
Write-Host "Running CMake..." -ForegroundColor Green

# Choose generator based on compiler
if ($MINGW_FOUND) {
    # Use MinGW-w64
    cmake -G "MinGW Makefiles" ..
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: CMake configuration failed for MinGW-w64." -ForegroundColor Red
        Read-Host -Prompt "Press Enter to exit"
        exit 1
    }
    
    Write-Host
    Write-Host "Building..." -ForegroundColor Green
    
    # Try to build with mingw32-make
    if (Get-Command mingw32-make -ErrorAction SilentlyContinue) {
        mingw32-make -j$env:NUMBER_OF_PROCESSORS
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Error: Build failed with mingw32-make." -ForegroundColor Red
            Write-Host "Trying with make..." -ForegroundColor Yellow
            
            # Try with make
            if (Get-Command make -ErrorAction SilentlyContinue) {
                make -j$env:NUMBER_OF_PROCESSORS
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "Error: Build failed." -ForegroundColor Red
                    Read-Host -Prompt "Press Enter to exit"
                    exit 1
                }
            } else {
                Write-Host "Error: make command not found." -ForegroundColor Red
                Read-Host -Prompt "Press Enter to exit"
                exit 1
            }
        }
    } elseif (Get-Command make -ErrorAction SilentlyContinue) {
        # Try with make directly
        make -j$env:NUMBER_OF_PROCESSORS
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Error: Build failed." -ForegroundColor Red
            Read-Host -Prompt "Press Enter to exit"
            exit 1
        }
    } else {
        Write-Host "Error: Neither mingw32-make nor make command found." -ForegroundColor Red
        Read-Host -Prompt "Press Enter to exit"
        exit 1
    }
    
    Write-Host
    Write-Host "=== Build completed successfully! ===" -ForegroundColor Green
    Write-Host "Executable: $BUILD_DIR\thumbnail_generator.exe"
    Write-Host
} else {
    # Use Visual Studio
    cmake -G "Ninja" ..
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: CMake configuration failed. Trying with Visual Studio generator..." -ForegroundColor Yellow
        cmake -G "Visual Studio 17 2022" -A x64 ..
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Error: CMake configuration failed." -ForegroundColor Red
            Read-Host -Prompt "Press Enter to exit"
            exit 1
        }
    }
    
    Write-Host
    Write-Host "Building..." -ForegroundColor Green
    
    if (Test-Path "build.ninja") {
        ninja
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Error: Build failed." -ForegroundColor Red
            Read-Host -Prompt "Press Enter to exit"
            exit 1
        }
    } else {
        cmake --build . --config Release
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Error: Build failed." -ForegroundColor Red
            Read-Host -Prompt "Press Enter to exit"
            exit 1
        }
    }
    
    Write-Host
    Write-Host "=== Build completed successfully! ===" -ForegroundColor Green
    Write-Host "Executable: $BUILD_DIR\Release\thumbnail_generator.exe"
    Write-Host
}

Read-Host -Prompt "Press Enter to exit"
