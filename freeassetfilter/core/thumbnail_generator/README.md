# Thumbnail Generator

A high-performance, cross-platform thumbnail generator written in C++17, with support for multiple image formats and concurrent processing.

## Features

- ✅ **Cross-platform**: Windows, Linux, and macOS support
- ✅ **Concurrent processing**: Uses multiple threads for faster thumbnail generation
- ✅ **Multiple image formats**: Supports JPEG, PNG, GIF, BMP, TIFF, WebP
- ✅ **RAW image support**: Optional support for RAW formats (ARW, DNG, CR2, NEF, ORF, RW2, PEF)
- ✅ **Customizable output**: Adjustable width, height, quality, and output format
- ✅ **Multiple output formats**: JSON, text, and CSV result formats
- ✅ **Python integration**: Easy integration with Python via subprocess
- ✅ **Minimal dependencies**: Can be built with just CMake and a C++17 compiler

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Building the Project](#building-the-project)
  - [Windows](#windows)
  - [Linux](#linux)
  - [macOS](#macos)
- [Usage](#usage)
  - [Command Line Options](#command-line-options)
  - [Basic Usage](#basic-usage)
  - [Advanced Usage](#advanced-usage)
  - [Python Integration](#python-integration)
- [Configuration](#configuration)
- [Dependencies](#dependencies)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## Installation

### Prerequisites

- **CMake** (version 3.12 or newer)
- **C++17 compiler** (GCC 7+, Clang 5+, MSVC 2019+)

### Optional Dependencies

- **OpenCV** (version 4.0 or newer): For image processing
- **LibRaw** (version 0.20 or newer): For RAW image support

Detailed installation instructions for dependencies can be found in [DEPENDENCIES.md](DEPENDENCIES.md).

## Building the Project

### Windows

#### Option 1: Using PowerShell

```powershell
# Build with default settings
./build.ps1

# Clean build directory and rebuild
./build.ps1 -Clean

# Build in Debug mode
./build.ps1 -BuildType Debug
```

#### Option 2: Using Windows CMD

```cmd
# Build with default settings
build.bat

# Clean build directory and rebuild
build.bat clean

# Build in Debug mode
build.bat debug
```

### Linux/macOS

```bash
# Make the script executable
chmod +x build.sh

# Build with default settings
./build.sh

# Clean build directory and rebuild
./build.sh --clean

# Build in Debug mode
./build.sh --debug
```

### Manual CMake Build

```bash
# Create build directory
mkdir -p build
cd build

# Configure CMake (Release mode)
cmake -G "Unix Makefiles" -DCMAKE_BUILD_TYPE=Release ..

# Build the project
make -j$(nproc)
```

## Usage

### Command Line Options

```
Usage: thumbnail_generator [options]
Options:
  -h, --help                Show this help message
  -i, --input <dir>         Input directory path
  -o, --output <dir>        Output directory path (default: cache directory)
  -w, --max-width <int>     Maximum width in pixels (default: 256)
  -H, --max-height <int>    Maximum height in pixels (default: 256)
  -t, --threads <int>       Number of threads to use (default: 4)
  -q, --quality <int>       Output image quality (0-100, default: 85)
  -f, --format <format>     Output image format (default: jpg)
  -r, --return-format <fmt> Return format (json, text, csv, default: json)
  -v, --verbose             Enable verbose logging

Supported image formats: jpg, jpeg, png, gif, bmp, tiff, webp
Supported RAW formats: arw, dng, cr2, nef, orf, rw2, pef
```

### Basic Usage

```bash
# Generate thumbnails with default settings
./thumbnail_generator --input ./images --output ./thumbnails

# Generate thumbnails with custom dimensions
./thumbnail_generator --input ./images --output ./thumbnails --max-width 512 --max-height 512

# Generate thumbnails with higher quality
./thumbnail_generator --input ./images --output ./thumbnails --quality 95
```

### Advanced Usage

```bash
# Use all available threads with verbose logging
./thumbnail_generator --input ./images --output ./thumbnails --threads $(nproc) --verbose

# Generate PNG thumbnails
./thumbnail_generator --input ./images --output ./thumbnails --format png

# Get results in text format
./thumbnail_generator --input ./images --output ./thumbnails --return-format text
```

### Python Integration

The thumbnail generator can be easily integrated with Python using the provided example script:

```python
#!/usr/bin/env python3

import subprocess
import json

# Define input and output directories
input_dir = "./images"
output_dir = "./thumbnails"

# Build the command
cmd = [
    "./build/thumbnail_generator",
    "--input", input_dir,
    "--output", output_dir,
    "--max-width", "512",
    "--max-height", "512",
    "--quality", "90",
    "--format", "jpg",
    "--return-format", "json"
]

# Execute the command
result = subprocess.run(cmd, capture_output=True, text=True, check=True)

# Parse the JSON result
results = json.loads(result.stdout)['results']

# Print results
for res in results:
    if res['success']:
        print(f"✓ {res['original_filename']} -> {res['thumbnail_filename']}")
    else:
        print(f"✗ {res['original_filename']}: {res['error_message']}")
```

A more complete Python example can be found in [python_example.py](python_example.py).

## Configuration

The thumbnail generator can be configured through command-line options. Here are the most common configurations:

| Parameter | Default | Description |
|-----------|---------|-------------|
| max-width | 256 | Maximum width of generated thumbnails |
| max-height | 256 | Maximum height of generated thumbnails |
| threads | 4 | Number of threads to use for concurrent processing |
| quality | 85 | Output image quality (0-100) |
| format | jpg | Output image format (jpg, png, webp) |
| return-format | json | Result output format (json, text, csv) |

## Dependencies

The project has a minimal set of dependencies:

| Dependency | Purpose | Optional |
|------------|---------|----------|
| CMake | Build system | No |
| C++17 Compiler | Compilation | No |
| OpenCV | Image processing | Yes |
| LibRaw | RAW image support | Yes |

Detailed dependency management information can be found in [DEPENDENCIES.md](DEPENDENCIES.md).

## Troubleshooting

### Common Issues

1. **CMake not found**
   - Ensure CMake is installed and added to your PATH
   - Download from: [cmake.org/download](https://cmake.org/download/)

2. **OpenCV not found**
   - Check installation instructions in [DEPENDENCIES.md](DEPENDENCIES.md)
   - Verify that OpenCV is properly installed and configured

3. **Build fails with linker errors**
   - Ensure all dependencies are built for the same architecture
   - Check that dependency versions are compatible

4. **Cannot process RAW images**
   - Ensure LibRaw is installed
   - Check that the RAW format is supported

### Getting Help

If you encounter any issues, please:

1. Check the [DEPENDENCIES.md](DEPENDENCIES.md) file for dependency-related issues
2. Ensure you're using the latest version of the project
3. Check the build output for detailed error messages
4. If the issue persists, create an issue on the project's repository

## Contributing

Contributions are welcome! Please feel free to submit issues, feature requests, or pull requests.

## License

This project is licensed under the [MIT License](LICENSE).
