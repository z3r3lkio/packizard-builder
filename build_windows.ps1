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
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python build environment not found at $python" }
$version = (& $python -c "from version import VERSION; print(VERSION)").Trim()
if ($version -notmatch '^\d+\.\d+\.\d+(-rc\d+)?$') { throw "Invalid application version: $version" }
if (-not $Architecture) { $Architecture = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" } }
$env:PACKIZARD_TARGET_ARCH = $Architecture
$releaseBase = [System.IO.Path]::GetFullPath((Join-Path $parentDir "release"))
$releaseRoot = if ($OutputDirectory) { [System.IO.Path]::GetFullPath((Join-Path $projectDir $OutputDirectory)) } else { [System.IO.Path]::GetFullPath((Join-Path $releaseBase "$version-windows-$Architecture")) }
if ((Split-Path -Parent $releaseRoot).TrimEnd('\') -ne $releaseBase.TrimEnd('\') -or -not (Split-Path -Leaf $releaseRoot)) { throw "Refusing to clean unexpected release path: $releaseRoot" }
$work = Join-Path $releaseRoot "work"
$dist = Join-Path $releaseRoot "dist"
$archive = Join-Path $releaseRoot "Packizard-Builder-$version-Windows-$Architecture.zip"

$oldPath = $env:Path
$pushed = $false
try {
    if (Test-Path -LiteralPath $releaseRoot) { Remove-Item -LiteralPath $releaseRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $work, $dist | Out-Null
    Push-Location $projectDir
    $pushed = $true

    # Prepare build-time assets while the normal PATH still exposes the .NET SDK.
    & $python scripts\prepare_windows_icon.py
    $rid = "win-$Architecture"
    & $python scripts\prepare_pkg_bridge.py --rid $rid

    # Keep PyInstaller isolated from unrelated developer-tool DLLs only after
    # the .NET bridge has been published.
    $env:Path = "$(Split-Path -Parent $python);$env:SystemRoot\System32;$env:SystemRoot"

    & $python -m PyInstaller --noconfirm --clean --workpath (Join-Path $work "packer") --distpath $dist Packizard_Packer_Worker.spec
    & $python -m PyInstaller --noconfirm --clean --workpath (Join-Path $work "profile") --distpath $dist Packizard_Profile_Worker.spec
    & $python -m PyInstaller --noconfirm --clean --workpath (Join-Path $work "builder") --distpath $dist Packizard_Builder.spec

    $exe = Join-Path $dist "Packizard-Builder.exe"
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "One-file Packizard executable not produced: $exe" }
    if (Test-Path -LiteralPath (Join-Path $dist "Packizard_Builder")) { throw "Sidecar Packizard_Builder directory was produced unexpectedly" }

    # Workers are build-time inputs for the one-file executable. Once embedded,
    # remove their standalone build outputs so dist represents the release shape.
    Get-ChildItem -LiteralPath $dist -Force | Where-Object { $_.FullName -ne $exe } | Remove-Item -Recurse -Force
    $remaining = @(Get-ChildItem -LiteralPath $dist -Force)
    if ($remaining.Count -ne 1 -or $remaining[0].FullName -ne $exe) {
        throw "Windows dist must contain only Packizard-Builder.exe after embedding workers and bridge"
    }

    Compress-Archive -LiteralPath $exe -DestinationPath $archive -Force
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($archive)
    try {
        $entries = @($zip.Entries | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Name) })
        if ($entries.Count -ne 1 -or $entries[0].Name -ne "Packizard-Builder.exe") {
            throw "Windows release archive must contain exactly Packizard-Builder.exe; found: $($entries.FullName -join ', ')"
        }
    }
    finally {
        $zip.Dispose()
    }

    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    Set-Content -LiteralPath (Join-Path $releaseRoot "SHA256SUMS-Windows-$Architecture.txt") -Value "$hash *$(Split-Path -Leaf $archive)" -Encoding ascii
    Write-Host "Built one-file executable $exe"
    Write-Host "Built release archive $archive"
    Write-Host "SHA-256 $hash"
}
finally {
    if ($pushed) { Pop-Location }
    $env:Path = $oldPath
}
