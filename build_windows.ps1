param(
    [string]$OutputDirectory = "",
    [ValidateSet("x64", "arm64")]
    [string]$Architecture = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$parentDir = Split-Path -Parent $projectDir
$python = Join-Path $projectDir ".venv312\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python build environment not found at $python"
}
$version = (& $python -c "from version import VERSION; print(VERSION)").Trim()
if ($version -notmatch '^\d+\.\d+\.\d+(-rc\d+)?$') {
    throw "Invalid application version: $version"
}
if (-not $Architecture) {
    $Architecture = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" }
}
$releaseBase = [System.IO.Path]::GetFullPath((Join-Path $parentDir "release"))
$releaseRoot = if ($OutputDirectory) {
    [System.IO.Path]::GetFullPath((Join-Path $projectDir $OutputDirectory))
} else {
    [System.IO.Path]::GetFullPath((Join-Path $releaseBase "$version-windows-$Architecture"))
}
if ((Split-Path -Parent $releaseRoot).TrimEnd('\') -ne $releaseBase.TrimEnd('\') -or
    -not (Split-Path -Leaf $releaseRoot)) {
    throw "Refusing to clean unexpected release path: $releaseRoot"
}
$work = Join-Path $releaseRoot "work"
$dist = Join-Path $releaseRoot "dist"
$archive = Join-Path $releaseRoot "Packizard-Builder-$version-Windows-$Architecture.zip"

$oldPath = $env:Path
$pushed = $false
try {
    $env:Path = "$(Split-Path -Parent $python);$env:SystemRoot\System32;$env:SystemRoot"
    if (Test-Path -LiteralPath $releaseRoot) {
        Remove-Item -LiteralPath $releaseRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $work, $dist | Out-Null
    Push-Location $projectDir
    $pushed = $true

    & $python scripts\prepare_windows_icon.py
    & $python -m PyInstaller --noconfirm --clean --workpath $work --distpath $dist Packizard_Builder.spec
    & $python -m PyInstaller --noconfirm --clean --workpath $work --distpath $dist Packizard_Packer_Worker.spec
    & $python -m PyInstaller --noconfirm --clean --workpath $work --distpath $dist Packizard_Profile_Worker.spec

    $workers = Join-Path $dist "Packizard_Builder\workers"
    New-Item -ItemType Directory -Force -Path $workers | Out-Null
    Copy-Item -Recurse -Force -LiteralPath (Join-Path $dist "Packizard-Packer-Worker") -Destination $workers
    Copy-Item -Recurse -Force -LiteralPath (Join-Path $dist "Packizard-Profile-Worker") -Destination $workers

    # Build and bundle Packizard's integrated LibProsperoPKG bridge for this native architecture.
    $rid = "win-$Architecture"
    & $python scripts\prepare_pkg_bridge.py --rid $rid
    $bridgeSource = Join-Path $projectDir "pkg_bridge\$rid"
    $bridgeTarget = Join-Path $dist "Packizard_Builder\pkg_bridge"
    New-Item -ItemType Directory -Force -Path $bridgeTarget | Out-Null
    Copy-Item -Recurse -Force -Path (Join-Path $bridgeSource "*") -Destination $bridgeTarget
    $lppLicenseTarget = Join-Path $dist "Packizard_Builder\licenses\LibProsperoPKG"
    New-Item -ItemType Directory -Force -Path $lppLicenseTarget | Out-Null
    Copy-Item -Force -LiteralPath (Join-Path $projectDir "vendor\LibProsperoPKG\LICENSE") -Destination (Join-Path $lppLicenseTarget "LICENSE")

    Compress-Archive -Path (Join-Path $dist "Packizard_Builder\*") -DestinationPath $archive -Force
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    Set-Content -LiteralPath (Join-Path $releaseRoot "SHA256SUMS-Windows-$Architecture.txt") `
        -Value "$hash *$(Split-Path -Leaf $archive)" -Encoding ascii
    Write-Host "Built $archive"
    Write-Host "SHA-256 $hash"
}
finally {
    if ($pushed) { Pop-Location }
    $env:Path = $oldPath
}
