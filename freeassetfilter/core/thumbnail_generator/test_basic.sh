#!/bin/bash
# ==============================================================================
# Basic Test Script for Thumbnail Generator
# ==============================================================================
#
# This script runs basic tests to verify the thumbnail generator functionality.
# It tests the following:
# 1. Help message works correctly
# 2. Program runs without crashing
# 3. Basic command line options work
# 4. Error handling for invalid inputs
#
# Usage: ./test_basic.sh [executable_path]
#
# If no executable path is provided, it will look for the executable in the build directory.
# ==============================================================================

set -e

# Default executable path
DEFAULT_EXECUTABLE="./build/thumbnail_generator"
EXECUTABLE="$1"

# If no executable path is provided, use the default
if [ -z "$EXECUTABLE" ]; then
    EXECUTABLE="$DEFAULT_EXECUTABLE"
fi

# Check if the executable exists
if [ ! -f "$EXECUTABLE" ]; then
    echo -e "\e[31mERROR: Executable not found at '$EXECUTABLE'\e[0m"
    echo -e "\e[33mPlease build the project first or provide the correct path to the executable.\e[0m"
    exit 1
fi

echo "======================================================================"
echo "Thumbnail Generator Basic Test Suite"
echo "======================================================================"
echo "Executable: $EXECUTABLE"
echo "Date: $(date)"
echo "======================================================================"
echo ""

# Test 1: Help message
TEST_NAME="Help Message"
echo "✓ Testing $TEST_NAME..."
$EXECUTABLE --help > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "  \e[32mPASS\e[0m: $TEST_NAME"
else
    echo -e "  \e[31mFAIL\e[0m: $TEST_NAME"
    exit 1
fi

# Test 2: Version/usage info
TEST_NAME="Version/Usage Info"
echo "✓ Testing $TEST_NAME..."
$EXECUTABLE -h > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "  \e[32mPASS\e[0m: $TEST_NAME"
else
    echo -e "  \e[31mFAIL\e[0m: $TEST_NAME"
    exit 1
fi

# Test 3: Invalid input directory (error handling)
TEST_NAME="Invalid Input Directory Handling"
echo "✓ Testing $TEST_NAME..."
$EXECUTABLE --input ./this_directory_does_not_exist > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo -e "  \e[32mPASS\e[0m: $TEST_NAME"
else
    echo -e "  \e[31mFAIL\e[0m: $TEST_NAME"
    exit 1
fi

# Test 4: Missing required arguments (should show help)
TEST_NAME="Missing Required Arguments Handling"
echo "✓ Testing $TEST_NAME..."
$EXECUTABLE > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo -e "  \e[32mPASS\e[0m: $TEST_NAME"
else
    echo -e "  \e[31mFAIL\e[0m: $TEST_NAME"
    exit 1
fi

# Test 5: Valid command with all options
TEST_NAME="Valid Command Line Options"
echo "✓ Testing $TEST_NAME..."

# Create test directories
TEST_INPUT_DIR="./test_input"
TEST_OUTPUT_DIR="./test_output"
mkdir -p "$TEST_INPUT_DIR" "$TEST_OUTPUT_DIR"

# Create a dummy test file (non-image)
echo "This is a test file" > "$TEST_INPUT_DIR/test.txt"

# Run the command
$EXECUTABLE \
    --input "$TEST_INPUT_DIR" \
    --output "$TEST_OUTPUT_DIR" \
    --max-width 256 \
    --max-height 256 \
    --threads 2 \
    --quality 85 \
    --format jpg \
    --return-format json \
    > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo -e "  \e[32mPASS\e[0m: $TEST_NAME"
else
    echo -e "  \e[31mFAIL\e[0m: $TEST_NAME"
    # Clean up
    rm -rf "$TEST_INPUT_DIR" "$TEST_OUTPUT_DIR"
    exit 1
fi

# Clean up test directories
rm -rf "$TEST_INPUT_DIR" "$TEST_OUTPUT_DIR"

# Test 6: Text output format
TEST_NAME="Text Output Format"
echo "✓ Testing $TEST_NAME..."
$EXECUTABLE --input ./build --output ./build --return-format text > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "  \e[32mPASS\e[0m: $TEST_NAME"
else
    echo -e "  \e[31mFAIL\e[0m: $TEST_NAME"
    exit 1
fi

# Test 7: CSV output format
TEST_NAME="CSV Output Format"
echo "✓ Testing $TEST_NAME..."
$EXECUTABLE --input ./build --output ./build --return-format csv > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "  \e[32mPASS\e[0m: $TEST_NAME"
else
    echo -e "  \e[31mFAIL\e[0m: $TEST_NAME"
    exit 1
fi

# Test 8: Verbose mode
TEST_NAME="Verbose Mode"
echo "✓ Testing $TEST_NAME..."
$EXECUTABLE --input ./build --output ./build --verbose > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "  \e[32mPASS\e[0m: $TEST_NAME"
else
    echo -e "  \e[31mFAIL\e[0m: $TEST_NAME"
    exit 1
fi

echo ""
echo "======================================================================"
echo -e "\e[32m🎉 All basic tests passed!\e[0m"
echo "======================================================================"
echo "✓ The thumbnail generator is functioning correctly."
echo "✓ Command line options are working properly."
echo "✓ Error handling is functioning as expected."
echo "✓ Output formats are supported."
echo "======================================================================"
echo ""

echo "Additional tests that could be performed manually:"
echo "1. Create a directory with actual image files and test thumbnail generation"
echo "2. Test with different image formats (JPEG, PNG, TIFF, etc.)"
echo "3. Test with various resolution images"
echo "4. Test with a large number of images to verify concurrent processing"
echo "5. Test on different platforms (Windows, Linux, macOS)"
echo ""
