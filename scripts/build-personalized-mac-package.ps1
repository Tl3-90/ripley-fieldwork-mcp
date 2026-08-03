[CmdletBinding()]
param(
    [string]$OutputPath,
    [string]$StandardOutputPath
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$packageDirectory = Split-Path -Parent $repositoryRoot
$templatePath = Join-Path $repositoryRoot "INSTALL-RIPLEY-MCP-MAC.command"
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $packageDirectory `
        "Ripley-Codex-Mac-Setup-Personalized.zip"
}
if ([string]::IsNullOrWhiteSpace($StandardOutputPath)) {
    $StandardOutputPath = Join-Path $packageDirectory `
        "Ripley-Codex-Mac-Setup.zip"
}
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
$StandardOutputPath = [IO.Path]::GetFullPath($StandardOutputPath)
$token = $null

function Write-MacInstallerZip {
    param(
        [Parameter(Mandatory)]
        [string]$Content,
        [Parameter(Mandatory)]
        [string]$DestinationPath,
        [Parameter(Mandatory)]
        [string]$PackageLabel
    )

    $temporaryPath = "$DestinationPath.partial-$PID"
    try {
        $outputDirectory = Split-Path -Parent $DestinationPath
        if (-not (Test-Path -LiteralPath $outputDirectory)) {
            New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
        }
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }

        Add-Type -AssemblyName System.IO.Compression
        $fileStream = [IO.File]::Open(
            $temporaryPath,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
        try {
            $archive = [IO.Compression.ZipArchive]::new(
                $fileStream,
                [IO.Compression.ZipArchiveMode]::Create,
                $false
            )
            try {
                $entry = $archive.CreateEntry(
                    "INSTALL-RIPLEY-MCP-MAC.command",
                    [IO.Compression.CompressionLevel]::Optimal
                )
                # ZIP external attributes for a regular Unix file with mode 0755.
                $entry.ExternalAttributes = -2115174400
                $entryStream = $entry.Open()
                try {
                    $writer = [IO.StreamWriter]::new(
                        $entryStream,
                        [Text.UTF8Encoding]::new($false)
                    )
                    try {
                        $writer.Write($Content)
                    }
                    finally {
                        $writer.Dispose()
                    }
                }
                finally {
                    $entryStream.Dispose()
                }
            }
            finally {
                $archive.Dispose()
            }
        }
        finally {
            $fileStream.Dispose()
        }

        # ZipArchive on Windows records the entry as DOS-origin even when Unix
        # mode bits are present. Mark it as Unix-origin so macOS restores 0755.
        $zipBytes = [IO.File]::ReadAllBytes($temporaryPath)
        $centralDirectoryEntries = 0
        for ($index = 0; $index -le $zipBytes.Length - 6; $index++) {
            if (
                $zipBytes[$index] -eq 0x50 -and
                $zipBytes[$index + 1] -eq 0x4b -and
                $zipBytes[$index + 2] -eq 0x01 -and
                $zipBytes[$index + 3] -eq 0x02
            ) {
                $zipBytes[$index + 5] = 3
                $centralDirectoryEntries++
            }
        }
        if ($centralDirectoryEntries -ne 1) {
            throw "$PackageLabel ZIP did not contain exactly one installer entry."
        }
        [IO.File]::WriteAllBytes($temporaryPath, $zipBytes)

        if (Test-Path -LiteralPath $DestinationPath) {
            Remove-Item -LiteralPath $DestinationPath -Force
        }
        Move-Item -LiteralPath $temporaryPath -Destination $DestinationPath
        Write-Host "$PackageLabel Mac setup package created: $DestinationPath"
    }
    finally {
        $zipBytes = $null
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

try {
    $token = [Environment]::GetEnvironmentVariable("RIPLEY_API_KEY", "User")
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "The Windows user environment variable RIPLEY_API_KEY is not set."
    }
    $token = $token.Trim()
    if ($token.Length -lt 16 -or $token -match "\s") {
        throw "RIPLEY_API_KEY does not look like a valid bearer token."
    }

    $template = [IO.File]::ReadAllText($templatePath)
    if ($template.Contains("`r")) {
        throw "The Mac installer template contains Windows CRLF line endings."
    }
    $placeholder = 'embedded_token_base64=""'
    $placeholderIndex = $template.IndexOf($placeholder, [StringComparison]::Ordinal)
    $secondPlaceholderIndex = if ($placeholderIndex -ge 0) {
        $template.IndexOf(
            $placeholder,
            $placeholderIndex + $placeholder.Length,
            [StringComparison]::Ordinal
        )
    }
    else {
        -1
    }
    if ($placeholderIndex -lt 0 -or $secondPlaceholderIndex -ge 0) {
        throw "The Mac installer token placeholder is missing or duplicated."
    }

    $encodedToken = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($token))
    $personalizedInstaller = $template.Replace(
        $placeholder,
        "embedded_token_base64=`"$encodedToken`""
    )

    Write-MacInstallerZip `
        -Content $template `
        -DestinationPath $StandardOutputPath `
        -PackageLabel "Standard"
    Write-MacInstallerZip `
        -Content $personalizedInstaller `
        -DestinationPath $OutputPath `
        -PackageLabel "Personalized"
}
finally {
    $token = $null
    $encodedToken = $null
    $personalizedInstaller = $null
}
