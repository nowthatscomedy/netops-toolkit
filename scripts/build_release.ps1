param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

function Resolve-IsccPath {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:ProgramFiles} "Inno Setup 6\ISCC.exe")
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    throw "ISCC.exe from Inno Setup 6 was not found. Please install Inno Setup first."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$normalizedVersion = $Version.Trim()
if ($normalizedVersion.StartsWith("v")) {
    $normalizedVersion = $normalizedVersion.Substring(1)
}

if ([string]::IsNullOrWhiteSpace($normalizedVersion)) {
    throw "A valid version is required, for example 1.0.0 or v1.0.0."
}

$buildDir = Join-Path $repoRoot "build"
$distDir = Join-Path $repoRoot "dist"
$stagingDir = Join-Path $buildDir "staging"
$stagingConfigDir = Join-Path $stagingDir "config"
$stagingLogsDir = Join-Path $stagingDir "logs"
$stagingLogsExportsDir = Join-Path $stagingLogsDir "exports"
$releaseDir = Join-Path $distDir "release"

if ($Clean) {
    foreach ($path in @($buildDir, $distDir)) {
        if (Test-Path $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
}

New-Item -ItemType Directory -Force -Path $stagingConfigDir | Out-Null
New-Item -ItemType Directory -Force -Path $stagingLogsExportsDir | Out-Null
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

Copy-Item -LiteralPath (Join-Path $repoRoot "config\ip_profiles.json") -Destination $stagingConfigDir -Force
Copy-Item -LiteralPath (Join-Path $repoRoot "config\vendor_presets.json") -Destination $stagingConfigDir -Force
Copy-Item -LiteralPath (Join-Path $repoRoot "config\wifi_profiles.json") -Destination $stagingConfigDir -Force

Set-Content -LiteralPath (Join-Path $stagingLogsDir ".gitkeep") -Value "" -Encoding UTF8
Set-Content -LiteralPath (Join-Path $stagingLogsExportsDir ".gitkeep") -Value "" -Encoding UTF8

$pyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "NetOpsToolkit",
    "--add-data", "$stagingConfigDir;config",
    "--add-data", "$stagingLogsDir;logs",
    "main.py"
)

$optionalBinaries = @(
    "iperf3.exe",
    "cygcrypto-3.dll",
    "cygwin1.dll",
    "cygz.dll"
)

foreach ($binaryName in $optionalBinaries) {
    $binaryPath = Join-Path $repoRoot $binaryName
    if (Test-Path $binaryPath) {
        $pyInstallerArgs += @("--add-binary", "$binaryPath;.")
    }
}

Write-Host "Building PyInstaller bundle for version $normalizedVersion..."
& python @pyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$isccPath = Resolve-IsccPath
$sourceDir = Join-Path $distDir "NetOpsToolkit"
$installerScript = Join-Path $repoRoot "installer\netops-toolkit.iss"

if (-not (Test-Path $sourceDir)) {
    throw "PyInstaller output folder was not found: $sourceDir"
}

Write-Host "Building installer..."
& $isccPath `
    "/DAppVersion=$normalizedVersion" `
    "/DSourceDir=$sourceDir" `
    "/DOutputDir=$releaseDir" `
    $installerScript

if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup build failed."
}

Get-ChildItem -LiteralPath $releaseDir -Filter "NetOpsToolkit-setup-*.exe" |
    Select-Object FullName, Length, LastWriteTime
