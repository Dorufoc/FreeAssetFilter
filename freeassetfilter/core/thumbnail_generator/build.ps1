<#
.SYNOPSIS
Thumbnail Generator Build Script for PowerShell

.DESCRIPTION
This script builds the thumbnail generator using CMake and either MinGW-w64 or Visual Studio.
It automatically detects the available build environment and configures CMake accordingly.

.PARAMETER Clean
Clean the build directory before building

.PARAMETER BuildType
Specify the build type: Debug or Release (default: Release)

.EXAMPLE
./build.ps1
Builds the project with default settings

.EXAMPLE
./build.ps1 -Clean
Cleans the build directory and rebuilds the project

.EXAMPLE
./build.ps1 -BuildType Debug
Builds the project in Debug mode

.NOTES
Author: Your Name
Date: $(Get-Date -Format "yyyy-MM-dd")
Version: 1.0
#>

param(
    [switch]$Clean,
    [ValidateSet("Debug", "Release")]
    [string]$BuildType = "Release"
)

# 配置脚本行为
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# 颜色常量
$COLOR_INFO = "Green"
$COLOR_WARNING = "Yellow"
$COLOR_ERROR = "Red"
$COLOR_SUCCESS = "Green"

Write-Host "=== Thumbnail Generator Build Script ===" -ForegroundColor $COLOR_INFO
Write-Host "Build Type: $BuildType" -ForegroundColor $COLOR_INFO
Write-Host "Date: $(Get-Date)" -ForegroundColor $COLOR_INFO
Write-Host

# 检查必要工具
function Check-Tool(
    [string]$ToolName,
    [string]$DownloadUrl
) {
    if (-not (Get-Command $ToolName -ErrorAction SilentlyContinue)) {
        Write-Host "❌ Error: $ToolName is not installed." -ForegroundColor $COLOR_ERROR
        Write-Host "   Download from: $DownloadUrl" -ForegroundColor $COLOR_WARNING
        Read-Host -Prompt "   Press Enter to exit"
        exit 1
    }
    Write-Host "✅ $ToolName is installed." -ForegroundColor $COLOR_SUCCESS
}

# 检查CMake
Check-Tool -ToolName "cmake" -DownloadUrl "https://cmake.org/download/"

# 设置构建目录
$BUILD_DIR = Join-Path -Path $PSScriptRoot -ChildPath "build"

# 清理构建目录（如果需要）
if ($Clean -and (Test-Path -Path $BUILD_DIR)) {
    Write-Host "🧹 Cleaning build directory..." -ForegroundColor $COLOR_INFO
    Remove-Item -Path $BUILD_DIR -Recurse -Force | Out-Null
    Write-Host "✅ Build directory cleaned." -ForegroundColor $COLOR_SUCCESS
}

# 创建构建目录
New-Item -ItemType Directory -Path $BUILD_DIR -Force | Out-Null

# 切换到构建目录
Write-Host "📁 Changing to build directory: $BUILD_DIR" -ForegroundColor $COLOR_INFO
Set-Location -Path $BUILD_DIR

# 检测构建环境
Write-Host
Write-Host "🔍 Detecting build environment..." -ForegroundColor $COLOR_INFO

$MINGW_FOUND = $false
$VS_FOUND = $false

# 检查MinGW-w64环境
if (Get-Command gcc -ErrorAction SilentlyContinue) {
    $gccVersion = gcc --version 2>$null
    if ($gccVersion -match "mingw-w64") {
        $MINGW_FOUND = $true
        Write-Host "✅ Found MinGW-w64 environment" -ForegroundColor $COLOR_SUCCESS
    }
}

# 检查Visual Studio环境
if (-not $MINGW_FOUND) {
    if ($env:VSINSTALLDIR) {
        $VS_FOUND = $true
        Write-Host "✅ Using existing Visual Studio environment" -ForegroundColor $COLOR_SUCCESS
    } else {
        # 尝试查找Visual Studio 2022
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
            $VS_FOUND = $true
            Write-Host "✅ Found Visual Studio 2022 at $vcvarsPath" -ForegroundColor $COLOR_SUCCESS
            Write-Host "🚀 Setting up Visual Studio environment..." -ForegroundColor $COLOR_INFO
            
            # 运行vcvars64.bat并重新启动脚本
            & cmd /c ""$vcvarsPath" && powershell.exe -ExecutionPolicy Bypass -NoExit -Command "Set-Location -Path '$BUILD_DIR'; & '$PSScriptRoot\build.ps1'""
            exit 0
        }
    }
}

# 确保至少找到一种构建环境
if (-not $MINGW_FOUND -and -not $VS_FOUND) {
    Write-Host "❌ Error: No C++ compiler found." -ForegroundColor $COLOR_ERROR
    Write-Host "   Please install one of the following:"
    Write-Host "   - MinGW-w64: https://www.mingw-w64.org/downloads/"
    Write-Host "   - Visual Studio: https://visualstudio.microsoft.com/downloads/"
    Read-Host -Prompt "   Press Enter to exit"
    exit 1
}

# 运行CMake配置
Write-Host
Write-Host "⚙️  Running CMake configuration..." -ForegroundColor $COLOR_INFO

if ($MINGW_FOUND) {
    # 使用MinGW-w64构建
    cmake -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=$BuildType ..
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ CMake configuration failed for MinGW-w64." -ForegroundColor $COLOR_ERROR
        Read-Host -Prompt "   Press Enter to exit"
        exit 1
    }
} else {
    # 使用Visual Studio构建
    cmake -G "Ninja" -DCMAKE_BUILD_TYPE=$BuildType ..
    if ($LASTEXITCODE -ne 0) {
        Write-Host "⚠️  Ninja generator failed, trying Visual Studio generator..." -ForegroundColor $COLOR_WARNING
        cmake -G "Visual Studio 17 2022" -A x64 ..
        if ($LASTEXITCODE -ne 0) {
            Write-Host "❌ CMake configuration failed for Visual Studio." -ForegroundColor $COLOR_ERROR
            Read-Host -Prompt "   Press Enter to exit"
            exit 1
        }
    }
}

Write-Host "✅ CMake configuration completed." -ForegroundColor $COLOR_SUCCESS

# 执行构建
Write-Host
Write-Host "🚀 Building the project..." -ForegroundColor $COLOR_INFO

if ($MINGW_FOUND) {
    # MinGW-w64构建
    $MAKE_COMMAND = "mingw32-make"
    if (-not (Get-Command $MAKE_COMMAND -ErrorAction SilentlyContinue)) {
        $MAKE_COMMAND = "make"
    }
    
    Write-Host "   Using: $MAKE_COMMAND -j$env:NUMBER_OF_PROCESSORS" -ForegroundColor $COLOR_INFO
    & $MAKE_COMMAND -j$env:NUMBER_OF_PROCESSORS
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Build failed." -ForegroundColor $COLOR_ERROR
        Read-Host -Prompt "   Press Enter to exit"
        exit 1
    }
} else {
    # Visual Studio构建
    if (Test-Path "build.ninja") {
        Write-Host "   Using: ninja" -ForegroundColor $COLOR_INFO
        ninja
    } else {
        Write-Host "   Using: cmake --build" -ForegroundColor $COLOR_INFO
        cmake --build . --config $BuildType
    }
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Build failed." -ForegroundColor $COLOR_ERROR
        Read-Host -Prompt "   Press Enter to exit"
        exit 1
    }
}

# 构建成功
Write-Host
Write-Host "🎉 Build completed successfully!" -ForegroundColor $COLOR_SUCCESS

# 确定可执行文件路径
$EXECUTABLE_PATH = Join-Path -Path $BUILD_DIR -ChildPath "thumbnail_generator.exe"
if (-not $MINGW_FOUND) {
    $EXECUTABLE_PATH = Join-Path -Path $BUILD_DIR -ChildPath "$BuildType\thumbnail_generator.exe"
}

if (Test-Path $EXECUTABLE_PATH) {
    Write-Host "📦 Executable: $EXECUTABLE_PATH" -ForegroundColor $COLOR_SUCCESS
    Write-Host
    Write-Host "✅ You can now run the thumbnail generator:"
    Write-Host "   $EXECUTABLE_PATH --help"
} else {
    Write-Host "⚠️  Executable not found at expected location." -ForegroundColor $COLOR_WARNING
    Write-Host "   Check the build output for the actual location."
}

Write-Host
Read-Host -Prompt "Press Enter to exit"
