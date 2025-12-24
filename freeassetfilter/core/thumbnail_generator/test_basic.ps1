<#
.SYNOPSIS
Thumbnail Generator Basic Test Script for PowerShell

.DESCRIPTION
This script runs basic tests to verify the thumbnail generator functionality on Windows.
It tests the following:
1. Help message works correctly
2. Program runs without crashing
3. Basic command line options work
4. Error handling for invalid inputs

.PARAMETER ExecutablePath
Path to the thumbnail_generator executable. If not provided, it will look for the executable in the build directory.

.EXAMPLE
./test_basic.ps1
Runs the tests with the default executable path.

.EXAMPLE
./test_basic.ps1 -ExecutablePath ".\build\thumbnail_generator.exe"
Runs the tests with a custom executable path.
#>

param(
    [string]$ExecutablePath
)

# Configuration
$DEFAULT_EXECUTABLE = ".\build\thumbnail_generator.exe"
$COLOR_SUCCESS = "Green"
$COLOR_ERROR = "Red"
$COLOR_WARNING = "Yellow"
$COLOR_INFO = "Cyan"

# Set executable path
if (-not $ExecutablePath) {
    $ExecutablePath = $DEFAULT_EXECUTABLE
}

Write-Host "======================================================================" -ForegroundColor $COLOR_INFO
Write-Host "Thumbnail Generator Basic Test Suite for PowerShell" -ForegroundColor $COLOR_INFO
Write-Host "======================================================================" -ForegroundColor $COLOR_INFO
Write-Host "Executable: $ExecutablePath" -ForegroundColor $COLOR_INFO
Write-Host "Date: $(Get-Date)" -ForegroundColor $COLOR_INFO
Write-Host "======================================================================" -ForegroundColor $COLOR_INFO
Write-Host

# Check if the executable exists
if (-not (Test-Path $ExecutablePath -PathType Leaf)) {
    Write-Host "ERROR: Executable not found at '$ExecutablePath'" -ForegroundColor $COLOR_ERROR
    Write-Host "Please build the project first or provide the correct path to the executable." -ForegroundColor $COLOR_WARNING
    exit 1
}

# Test results tracking
$testResults = @()

# Function to run a single test
function Run-Test {
    param(
        [string]$TestName,
        [scriptblock]$TestScript,
        [bool]$ExpectedSuccess = $true
    )
    
    Write-Host "✓ Testing $TestName..." -ForegroundColor $COLOR_INFO
    
    try {
        $result = Invoke-Command -ScriptBlock $TestScript
        $actualSuccess = $result -eq 0
        
        if ($actualSuccess -eq $ExpectedSuccess) {
            Write-Host "  ✓ PASS: $TestName" -ForegroundColor $COLOR_SUCCESS
            $testResults += @{ Name = $TestName; Result = "PASS" }
        } else {
            Write-Host "  ✗ FAIL: $TestName" -ForegroundColor $COLOR_ERROR
            $testResults += @{ Name = $TestName; Result = "FAIL" }
        }
    } catch {
        Write-Host "  ✗ ERROR: $TestName - $($_.Exception.Message)" -ForegroundColor $COLOR_ERROR
        $testResults += @{ Name = $TestName; Result = "ERROR" }
    }
}

# Test 1: Help message
Run-Test -TestName "Help Message" -TestScript {
    & $ExecutablePath --help > $null 2>&1
    return $LASTEXITCODE
} -ExpectedSuccess $true

# Test 2: Short help message (-h)
Run-Test -TestName "Short Help Message (-h)" -TestScript {
    & $ExecutablePath -h > $null 2>&1
    return $LASTEXITCODE
} -ExpectedSuccess $true

# Test 3: Invalid input directory (error handling)
Run-Test -TestName "Invalid Input Directory Handling" -TestScript {
    & $ExecutablePath --input .\this_directory_does_not_exist > $null 2>&1
    return $LASTEXITCODE
} -ExpectedSuccess $false

# Test 4: Missing required arguments
Run-Test -TestName "Missing Required Arguments Handling" -TestScript {
    & $ExecutablePath > $null 2>&1
    return $LASTEXITCODE
} -ExpectedSuccess $false

# Test 5: Valid command with all options
Run-Test -TestName "Valid Command Line Options" -TestScript {
    # Create test directories
    $testInputDir = ".\test_input"
    $testOutputDir = ".\test_output"
    New-Item -ItemType Directory -Path $testInputDir -Force | Out-Null
    New-Item -ItemType Directory -Path $testOutputDir -Force | Out-Null
    
    # Create a dummy test file
    Set-Content -Path "$testInputDir\test.txt" -Value "This is a test file" -Force
    
    # Run the command
    & $ExecutablePath `
        --input $testInputDir `
        --output $testOutputDir `
        --max-width 256 `
        --max-height 256 `
        --threads 2 `
        --quality 85 `
        --format jpg `
        --return-format json `
        > $null 2>&1
    $result = $LASTEXITCODE
    
    # Clean up
    Remove-Item -Path $testInputDir -Recurse -Force | Out-Null
    Remove-Item -Path $testOutputDir -Recurse -Force | Out-Null
    
    return $result
} -ExpectedSuccess $true

# Test 6: Text output format
Run-Test -TestName "Text Output Format" -TestScript {
    & $ExecutablePath --input .\build --output .\build --return-format text > $null 2>&1
    return $LASTEXITCODE
} -ExpectedSuccess $true

# Test 7: CSV output format
Run-Test -TestName "CSV Output Format" -TestScript {
    & $ExecutablePath --input .\build --output .\build --return-format csv > $null 2>&1
    return $LASTEXITCODE
} -ExpectedSuccess $true

# Test 8: Verbose mode
Run-Test -TestName "Verbose Mode" -TestScript {
    & $ExecutablePath --input .\build --output .\build --verbose > $null 2>&1
    return $LASTEXITCODE
} -ExpectedSuccess $true

Write-Host
Write-Host "======================================================================" -ForegroundColor $COLOR_INFO

# Calculate test results
$totalTests = $testResults.Count
$passedTests = ($testResults | Where-Object { $_.Result -eq "PASS" }).Count
$failedTests = ($testResults | Where-Object { $_.Result -eq "FAIL" }).Count
$errorTests = ($testResults | Where-Object { $_.Result -eq "ERROR" }).Count

if ($failedTests -eq 0 -and $errorTests -eq 0) {
    Write-Host "🎉 All $totalTests tests passed successfully!" -ForegroundColor $COLOR_SUCCESS
} else {
    Write-Host "Test Summary:" -ForegroundColor $COLOR_WARNING
    Write-Host "  Total Tests: $totalTests" -ForegroundColor $COLOR_INFO
    Write-Host "  Passed: $passedTests" -ForegroundColor $COLOR_SUCCESS
    Write-Host "  Failed: $failedTests" -ForegroundColor $COLOR_ERROR
    Write-Host "  Errors: $errorTests" -ForegroundColor $COLOR_ERROR
}

Write-Host "======================================================================" -ForegroundColor $COLOR_INFO
Write-Host

Write-Host "Additional tests that could be performed manually:" -ForegroundColor $COLOR_WARNING
Write-Host "1. Create a directory with actual image files and test thumbnail generation" -ForegroundColor $COLOR_INFO
Write-Host "2. Test with different image formats (JPEG, PNG, TIFF, etc.)" -ForegroundColor $COLOR_INFO
Write-Host "3. Test with various resolution images" -ForegroundColor $COLOR_INFO
Write-Host "4. Test with a large number of images to verify concurrent processing" -ForegroundColor $COLOR_INFO
Write-Host "5. Test on different platforms (Windows, Linux, macOS)" -ForegroundColor $COLOR_INFO
Write-Host
