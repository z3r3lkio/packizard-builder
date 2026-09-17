[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('x64', 'arm64')]
    [string]$Architecture,

    [switch]$RequireSigning,

    [switch]$AllowSelfSignedUat
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Find-SignTool {
    $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
    if (-not (Test-Path $kits)) {
        throw "Windows SDK bin directory not found: $kits"
    }

    $preferredArch = if ($Architecture -eq 'arm64') { 'arm64' } else { 'x64' }
    $candidates = Get-ChildItem -Path $kits -Recurse -Filter signtool.exe -File |
        Where-Object { $_.FullName -match "\\$preferredArch\\signtool\.exe$" } |
        Sort-Object FullName -Descending

    if (-not $candidates) {
        $candidates = Get-ChildItem -Path $kits -Recurse -Filter signtool.exe -File |
            Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
            Sort-Object FullName -Descending
    }

    $tool = $candidates | Select-Object -First 1
    if (-not $tool) {
        throw 'signtool.exe was not found in the Windows SDK.'
    }
    return $tool.FullName
}

function Invoke-SignTool {
    param(
        [Parameter(Mandatory = $true)][string]$SignTool,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $SignTool @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "signtool.exe failed with exit code $LASTEXITCODE"
    }
}

function Assert-ExpectedAuthenticodeSigner {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedThumbprint,
        [switch]$AllowUntrustedSelfSigned
    )

    $signature = Get-AuthenticodeSignature -FilePath $Path
    if (-not $signature.SignerCertificate) {
        throw "No Authenticode signer certificate found on $Path"
    }
    if ($signature.SignerCertificate.Thumbprint -ne $ExpectedThumbprint) {
        throw "Unexpected Authenticode signer on $Path. Expected $ExpectedThumbprint, got $($signature.SignerCertificate.Thumbprint)."
    }

    if ($signature.Status -eq [System.Management.Automation.SignatureStatus]::Valid) {
        return
    }

    if ($AllowUntrustedSelfSigned) {
        if ($signature.Status -eq [System.Management.Automation.SignatureStatus]::NotTrusted) {
            Write-Host "UAT signature verified on $Path; signer is intentionally self-signed and untrusted by the hosted runner."
            return
        }

        if (
            $signature.Status -eq [System.Management.Automation.SignatureStatus]::UnknownError -and
            $signature.StatusMessage -match '(?i)(untrusted|root certificate|trust provider|certificate chain)'
        ) {
            Write-Host "UAT signature verified on $Path; Windows reported the expected untrusted-root chain status."
            return
        }
    }

    throw "Authenticode signature status for $Path is $($signature.Status): $($signature.StatusMessage)"
}

$pfxBase64 = $env:PACKIZARD_CODESIGN_PFX_B64
$pfxPassword = $env:PACKIZARD_CODESIGN_PFX_PASSWORD

if ([string]::IsNullOrWhiteSpace($pfxBase64) -or [string]::IsNullOrWhiteSpace($pfxPassword)) {
    if ($RequireSigning) {
        throw 'Windows release signing is required, but PACKIZARD_CODESIGN_PFX_B64 / PACKIZARD_CODESIGN_PFX_PASSWORD are not configured.'
    }
    Write-Warning 'Windows code-signing certificate is not configured. UAT/PR artifact will remain unsigned.'
    exit 0
}

$releaseRoot = Join-Path $PSScriptRoot '..\release'
$releaseDir = Get-ChildItem -Path $releaseRoot -Directory -Filter "*-windows-$Architecture" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $releaseDir) {
    throw "Windows $Architecture release directory not found under $releaseRoot"
}

$zip = Get-ChildItem -Path $releaseDir.FullName -File -Filter "Packizard-Builder-*-Windows-$Architecture.zip" |
    Select-Object -First 1
if (-not $zip) {
    throw "Windows $Architecture package ZIP not found in $($releaseDir.FullName)"
}

$tempRoot = Join-Path $env:RUNNER_TEMP "packizard-sign-$Architecture-$([guid]::NewGuid().ToString('N'))"
$extractRoot = Join-Path $tempRoot 'payload'
$pfxPath = Join-Path $tempRoot 'packizard-codesign.pfx'
New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
$signingCertificate = $null

try {
    [IO.File]::WriteAllBytes($pfxPath, [Convert]::FromBase64String($pfxBase64))

    $keyFlags = [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet
    $signingCertificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
        $pfxPath,
        $pfxPassword,
        $keyFlags
    )
    if (-not $signingCertificate.HasPrivateKey) {
        throw 'Configured PFX does not contain a private key.'
    }

    $expectedThumbprint = $signingCertificate.Thumbprint
    $isSelfSigned = $signingCertificate.Subject -eq $signingCertificate.Issuer
    $isUatContext = $AllowSelfSignedUat -or $env:GITHUB_REF -eq 'refs/heads/UAT' -or $env:GITHUB_BASE_REF -eq 'UAT'
    Write-Host "Authenticode certificate subject: $($signingCertificate.Subject)"
    Write-Host "Authenticode certificate thumbprint: $expectedThumbprint"

    if ($isSelfSigned) {
        if ($RequireSigning) {
            throw 'Tagged releases require a publicly trusted Authenticode certificate; the configured Packizard certificate is self-signed.'
        }
        if (-not $isUatContext) {
            throw 'The configured Packizard certificate is self-signed and this build is outside the UAT trust boundary.'
        }
        Write-Host 'Self-signed Packizard certificate accepted for UAT validation only.'
        Write-Host 'Skipping Windows trust-store mutation and RFC3161 timestamping for self-signed UAT signing.'
    }

    Expand-Archive -LiteralPath $zip.FullName -DestinationPath $extractRoot -Force

    $executables = @(Get-ChildItem -Path $extractRoot -Recurse -File -Filter '*.exe')
    if ($executables.Count -lt 4) {
        throw "Expected Packizard main executable plus helper executables; found only $($executables.Count) .exe file(s)."
    }

    $requiredNames = @(
        'Packizard_Builder.exe',
        'ampr_pack.exe',
        'ampr_pack_profile.exe',
        'Packizard.PkgBridge.exe'
    )
    foreach ($name in $requiredNames) {
        if (-not ($executables.Name -contains $name)) {
            throw "Required executable missing from package: $name"
        }
    }

    $signTool = Find-SignTool
    $timestampUrl = if ([string]::IsNullOrWhiteSpace($env:PACKIZARD_TIMESTAMP_URL)) {
        'http://timestamp.digicert.com'
    } else {
        $env:PACKIZARD_TIMESTAMP_URL
    }

    foreach ($exe in $executables) {
        Write-Host "Signing $($exe.FullName)"

        $signArguments = @(
            'sign',
            '/fd', 'SHA256',
            '/f', $pfxPath,
            '/p', $pfxPassword
        )
        if (-not $isSelfSigned) {
            $signArguments += @(
                '/td', 'SHA256',
                '/tr', $timestampUrl
            )
        }
        $signArguments += $exe.FullName

        Invoke-SignTool -SignTool $signTool -Arguments $signArguments

        if ($isSelfSigned) {
            Assert-ExpectedAuthenticodeSigner `
                -Path $exe.FullName `
                -ExpectedThumbprint $expectedThumbprint `
                -AllowUntrustedSelfSigned
        } else {
            Invoke-SignTool -SignTool $signTool -Arguments @('verify', '/pa', '/all', '/v', $exe.FullName)
            Assert-ExpectedAuthenticodeSigner -Path $exe.FullName -ExpectedThumbprint $expectedThumbprint
        }
    }

    Remove-Item -LiteralPath $zip.FullName -Force
    Compress-Archive -Path (Join-Path $extractRoot '*') -DestinationPath $zip.FullName -CompressionLevel Optimal

    $manifest = Join-Path $releaseDir.FullName "SHA256SUMS-Windows-$Architecture.txt"
    $hash = (Get-FileHash -LiteralPath $zip.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $($zip.Name)" | Set-Content -LiteralPath $manifest -Encoding ascii
    Write-Host "Signed and repacked $($zip.FullName)"
    Write-Host "SHA-256 $hash"
}
finally {
    if ($signingCertificate) {
        $signingCertificate.Dispose()
    }
    if (Test-Path $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
