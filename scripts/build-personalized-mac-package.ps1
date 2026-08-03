[CmdletBinding()]
param(
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$templatePath = Join-Path $repositoryRoot "INSTALL-RIPLEY-MCP-MAC.command"
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path (Split-Path -Parent $repositoryRoot) `
        "Ripley-Codex-Mac-Setup-Personalized.zip"
}
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
$temporaryPath = "$OutputPath.partial-$PID"
$token = $null

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

    $outputDirectory = Split-Path -Parent $OutputPath
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
                    $writer.Write($personalizedInstaller)
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

    # ZipArchive on Windows records the entry as DOS-origin even when Unix mode
    # bits are present. Mark the central-directory entry as Unix-origin so macOS
    # restores the executable bit when the ZIP is extracted.
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
        throw "The personalized ZIP did not contain exactly one installer entry."
    }
    [IO.File]::WriteAllBytes($temporaryPath, $zipBytes)

    if (Test-Path -LiteralPath $OutputPath) {
        Remove-Item -LiteralPath $OutputPath -Force
    }
    Move-Item -LiteralPath $temporaryPath -Destination $OutputPath
    Write-Host "Personalized Mac setup package created: $OutputPath"
}
finally {
    $token = $null
    $encodedToken = $null
    $personalizedInstaller = $null
    $zipBytes = $null
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
}
