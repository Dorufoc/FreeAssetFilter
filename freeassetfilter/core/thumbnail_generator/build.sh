#!/bin/bash
# ==============================================================================
# Thumbnail Generator Build Script for Linux/macOS
# ==============================================================================
#
# This script builds the thumbnail generator using CMake and GCC.
# It automatically detects the available build environment and
# configures CMake accordingly.
#
# Usage:
#   ./build.sh [--clean] [--debug|--release]
#
# Options:
#   --clean      Clean the build directory before building
#   --debug      Build in Debug mode (default: Release)
#   --release    Build in Release mode
#   -h, --help   Show this help message
#
# ==============================================================================

# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------
set -e  # Exit immediately if a command exits with a non-zero status

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
BUILD_DIR="$PROJECT_ROOT/build"
BUILD_TYPE="Release"
CLEAN_BUILD=0

# ------------------------------------------------------------------------------
# Print help message
# ------------------------------------------------------------------------------
print_help() {
    echo "Usage: $0 [--clean] [--debug|--release]"
    echo ""
    echo "Options:"
    echo "  --clean      Clean the build directory before building"
    echo "  --debug      Build in Debug mode (default: Release)"
    echo "  --release    Build in Release mode"
    echo "  -h, --help   Show this help message"
}

# ------------------------------------------------------------------------------
# Parse command line arguments
# ------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean)
            CLEAN_BUILD=1
            shift
            ;;
        --debug)
            BUILD_TYPE="Debug"
            shift
            ;;
        --release)
            BUILD_TYPE="Release"
            shift
            ;;
        -h|--help)
            print_help
            exit 0
            ;;
        *)
            echo "Error: Invalid option '$1'"
            print_help
            exit 1
            ;;
    esac
done

# ------------------------------------------------------------------------------
# Display script information
# ------------------------------------------------------------------------------
echo "======================================================================"
echo "Thumbnail Generator Build Script for Linux/macOS"
echo "======================================================================"
echo "Build Type: $BUILD_TYPE"
echo "Clean Build: $CLEAN_BUILD"
echo "Project Root: $PROJECT_ROOT"
echo "Build Directory: $BUILD_DIR"
echo "Date: $(date)"
echo "======================================================================"
echo ""

# ------------------------------------------------------------------------------
# Check for required tools
# ------------------------------------------------------------------------------
check_tool() {
    local tool_name="$1"
    local download_url="$2"
    
    if ! command -v "$tool_name" &> /dev/null; then
        echo -e "\e[31mERROR: $tool_name is not installed. Please install $tool_name first.\e[0m"
        echo -e "\e[33mDownload from: $download_url\e[0m"
        exit 1
    fi
    echo -e "\e[32m✓ $tool_name is installed.\e[0m"
}

echo "Checking required tools..."
check_tool "cmake" "https://cmake.org/download/"
check_tool "gcc" "https://gcc.gnu.org/"
check_tool "pkg-config" "https://www.freedesktop.org/wiki/Software/pkg-config/"
echo ""

# ------------------------------------------------------------------------------
# Check for OpenCV (optional)
# ------------------------------------------------------------------------------
echo "Checking optional dependencies..."
if pkg-config --exists opencv4 || pkg-config --exists opencv; then
    echo -e "\e[32m✓ OpenCV found, enabling full image support.\e[0m"
else
    echo -e "\e[33m⚠ OpenCV not found, building with limited functionality.\e[0m"
fi
echo ""

# ------------------------------------------------------------------------------
# Clean build directory if requested
# ------------------------------------------------------------------------------
if [[ "$CLEAN_BUILD" -eq 1 ]]; then
    echo -e "\e[34m🧹 Cleaning build directory...\e[0m"
    if [[ -d "$BUILD_DIR" ]]; then
        rm -rf "$BUILD_DIR"/*
    fi
    echo -e "\e[32m✓ Build directory cleaned.\e[0m"
    echo ""
fi

# ------------------------------------------------------------------------------
# Create build directory
# ------------------------------------------------------------------------------
mkdir -p "$BUILD_DIR"

# ------------------------------------------------------------------------------
# Run CMake configuration
# ------------------------------------------------------------------------------
echo -e "\e[34m⚙️  Running CMake configuration...\e[0m"
cd "$BUILD_DIR" || exit 1

# Configure CMake
cmake \
    -G "Unix Makefiles" \
    -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
    -DCMAKE_CXX_STANDARD=17 \
    "$PROJECT_ROOT"

if [[ $? -ne 0 ]]; then
    echo -e "\e[31mERROR: CMake configuration failed.\e[0m"
    exit 1
fi

echo -e "\e[32m✓ CMake configuration completed successfully.\e[0m"
echo ""

# ------------------------------------------------------------------------------
# Build the project
# ------------------------------------------------------------------------------
echo -e "\e[34m🚀 Building the project...\e[0m"

# Use all available CPU cores
MAKE_JOBS="$(nproc 2>/dev/null || echo 4)"
echo -e "   Using $MAKE_JOBS parallel jobs..."

make -j"$MAKE_JOBS"

if [[ $? -ne 0 ]]; then
    echo -e "\e[31mERROR: Build failed.\e[0m"
    exit 1
fi

echo ""
echo -e "\e[32m🎉 Build completed successfully!\e[0m"
echo "======================================================================"

# ------------------------------------------------------------------------------
# Locate and display the executable path
# ------------------------------------------------------------------------------
EXECUTABLE="$BUILD_DIR/thumbnail_generator"

if [[ -f "$EXECUTABLE" ]]; then
    echo -e "\e[32m📦 Executable: $EXECUTABLE\e[0m"
    echo ""
    echo -e "\e[32m✅ You can now run the thumbnail generator:\e[0m"
    echo "   $EXECUTABLE --help"
else
    echo -e "\e[33m⚠️  Executable not found at expected location.\e[0m"
    echo "   Check the build output for the actual location."
fi

echo ""