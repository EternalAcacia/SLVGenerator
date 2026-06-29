$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Installing build dependencies..."
python -m pip install -q pyinstaller pillow numpy customtkinter

Write-Host "Building SLVGenerator.exe..."
python -m PyInstaller --noconfirm --clean SLVGenerator.spec

$Exe = Join-Path $Root "dist\SLVGenerator.exe"
if (-not (Test-Path $Exe)) {
    throw "Build failed: dist\SLVGenerator.exe not found"
}

$Version = if ($env:RELEASE_VERSION) { $env:RELEASE_VERSION } else { "v1.0.0" }
$ZipName = "SLVGenerator-$Version-windows.zip"
$ZipPath = Join-Path $Root "dist\$ZipName"

if (Test-Path $ZipPath) {
    Remove-Item $ZipPath
}

$Readme = @"
SLVGenerator $Version (Windows)

Run SLVGenerator.exe to start the GUI.

Requirements:
- Windows 10/11
- FFmpeg and FFprobe must be installed and available in PATH for MP4 export

Optional:
- Create a fonts folder next to SLVGenerator.exe and place custom .ttf/.otf fonts there
"@

$TempDir = Join-Path $env:TEMP "slvgenerator-release"
if (Test-Path $TempDir) {
    Remove-Item $TempDir -Recurse -Force
}
New-Item -ItemType Directory -Path $TempDir | Out-Null
Copy-Item $Exe (Join-Path $TempDir "SLVGenerator.exe")
Set-Content -Path (Join-Path $TempDir "README.txt") -Value $Readme -Encoding UTF8
Compress-Archive -Path (Join-Path $TempDir "*") -DestinationPath $ZipPath -Force
Remove-Item $TempDir -Recurse -Force

Write-Host "Built: $Exe"
Write-Host "Package: $ZipPath"
