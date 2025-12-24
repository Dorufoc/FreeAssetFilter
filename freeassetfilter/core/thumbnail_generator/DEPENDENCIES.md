# Dependencies Management

This document provides detailed instructions on how to install the dependencies required for building the Thumbnail Generator.

## Table of Contents

- [Required Dependencies](#required-dependencies)
- [Optional Dependencies](#optional-dependencies)
- [Installation Instructions](#installation-instructions)
  - [Windows](#windows)
  - [Linux](#linux)
  - [macOS](#macos)
- [CMake Configuration](#cmake-configuration)
- [Troubleshooting](#troubleshooting)

## Required Dependencies

| Dependency | Version | Purpose | Installation |
|------------|---------|---------|--------------|
| CMake      | ≥ 3.12  | Build system | [cmake.org/download](https://cmake.org/download/) |
| C++17 Compiler | GCC 7+, Clang 5+, MSVC 2019+ | Compilation | Built-in with IDEs or via package managers |

## Optional Dependencies

| Dependency | Version | Purpose | Installation |
|------------|---------|---------|--------------|
| OpenCV     | ≥ 4.0   | Image processing | See below for detailed instructions |
| LibRaw     | ≥ 0.20  | RAW image support | Package managers or source compilation |

## Installation Instructions

### Windows

#### Option 1: Using MSYS2 (Recommended for MinGW-w64)

1. Install MSYS2 from [msys2.org](https://www.msys2.org/)
2. Open MSYS2 MINGW64 terminal
3. Update package database:
   ```bash
   pacman -Syu
   ```
4. Install required packages:
   ```bash
   pacman -S mingw-w64-x86_64-cmake mingw-w64-x86_64-gcc mingw-w64-x86_64-opencv mingw-w64-x86_64-libraw
   ```

#### Option 2: Using Visual Studio

1. Install Visual Studio 2019 or later with C++ development workload
2. Install CMake from [cmake.org/download](https://cmake.org/download/)
3. Install OpenCV:
   - Download pre-built binaries from [opencv.org/releases](https://opencv.org/releases/)
   - Add OpenCV's `bin` directory to your PATH environment variable

### Linux

#### Ubuntu/Debian

```bash
# Update package database
sudo apt update

# Install required packages
sudo apt install -y cmake g++ pkg-config libopencv-dev libraw-dev
```

#### Fedora/RHEL

```bash
# Install required packages
sudo dnf install -y cmake gcc-c++ opencv-devel libraw-devel
```

#### Arch Linux

```bash
# Install required packages
sudo pacman -S cmake gcc opencv libraw
```

### macOS

#### Using Homebrew (Recommended)

```bash
# Install Homebrew from brew.sh if not already installed

# Install required packages
brew install cmake gcc opencv libraw
```

#### Using MacPorts

```bash
# Install required packages
sudo port install cmake gcc12 opencv libraw
```

## CMake Configuration

The project's CMake configuration automatically detects dependencies and adapts the build accordingly:

- If OpenCV is not found, it builds with a simplified implementation that provides limited functionality
- If LibRaw is not found, it disables RAW image support

### Manual CMake Configuration

You can manually specify dependency locations if they are installed in non-standard paths:

```bash
cmake .. \
  -DOpenCV_DIR=/path/to/opencv/lib/cmake/opencv4 \
  -DLibRaw_DIR=/path/to/libraw/lib/cmake/libraw
```

## Troubleshooting

### CMake cannot find OpenCV

**Issue**: CMake reports "OpenCV not found"

**Solutions**:

1. Ensure OpenCV is installed correctly
2. Add OpenCV's CMake directory to your PATH or specify it with `-DOpenCV_DIR`
3. On Windows, make sure you're using the correct architecture (32-bit vs 64-bit)
4. On Linux/macOS, ensure pkg-config can find OpenCV:
   ```bash
   pkg-config --cflags --libs opencv4
   ```

### Build fails with linker errors related to OpenCV

**Issue**: Linker errors like "undefined reference to cv::imread"

**Solutions**:

1. Ensure you're linking against the correct OpenCV libraries
2. Check that the OpenCV version matches what was used to build the project
3. On Windows, ensure OpenCV DLLs are in your PATH

### LibRaw support not enabled

**Issue**: CMake reports "LibRaw not found"

**Solutions**:

1. Install LibRaw development packages
2. Specify LibRaw's location with `-DLibRaw_DIR`
3. Disable LibRaw support explicitly if it's not needed: `-DENABLE_RAW_SUPPORT=OFF`

## Build Without Optional Dependencies

The project can be built without OpenCV or LibRaw:

```bash
# Build with minimal dependencies (no OpenCV or LibRaw support)
cmake ..
make
```

In this mode, the thumbnail generator will still compile but won't be able to process images. This is useful for testing the build system or for environments where dependencies are not available.

## Additional Notes

- Always make sure your compiler and dependencies are built for the same architecture
- On Windows, when using MinGW-w64, ensure all dependencies are built with the same MinGW-w64 toolchain
- For production builds, it's recommended to use release builds with all optional dependencies enabled

For more information, please refer to the [CMakeLists.txt](CMakeLists.txt) file or the project's [README.md](README.md).
