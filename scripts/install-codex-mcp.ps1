[CmdletBinding()]
param(
    [string]$ApiKey,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$serverName = "ripley"
$serverUrl = "https://digi.hopto.me/ripley-api/mcp"
$healthUrl = "https://digi.hopto.me/ripley-api/health"
$environmentName = "RIPLEY_API_KEY"
$configDirectory = Join-Path $env:USERPROFILE ".codex"
$configPath = Join-Path $configDirectory "config.toml"
$oldContent = $null
$configExisted = $false
$previousUserToken = $null
$changesApplied = $false

function Read-PrivateToken {
    $saved = [Environment]::GetEnvironmentVariable($environmentName, "User")
    if (-not [string]::IsNullOrWhiteSpace($saved)) {
        Write-Host "A saved Ripley connection key was found. It will be reused."
        return $saved.Trim()
    }

    Write-Host "Paste the Ripley connection key Thomas gave you."
    Write-Host "The key will not be displayed while you paste or type it."
    $secureValue = Read-Host "Ripley connection key" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        return ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)).Trim()
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Remove-RipleySection {
    param([string]$Content)

    if ([string]::IsNullOrEmpty($Content)) {
        return ""
    }

    $result = [Collections.Generic.List[string]]::new()
    $skip = $false
    foreach ($line in [Text.RegularExpressions.Regex]::Split($Content, "\r?\n")) {
        if ($line.Trim() -eq "[mcp_servers.$serverName]") {
            $skip = $true
            continue
        }
        if ($skip -and $line.TrimStart().StartsWith("[")) {
            $skip = $false
        }
        if (-not $skip) {
            $result.Add($line)
        }
    }
    return ($result -join [Environment]::NewLine).TrimEnd()
}

function Send-EnvironmentRefresh {
    if (-not ("RipleyEnvironment.NativeMethods" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace RipleyEnvironment {
    public static class NativeMethods {
        [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
        public static extern IntPtr SendMessageTimeout(
            IntPtr hWnd, uint message, UIntPtr wParam, string lParam,
            uint flags, uint timeout, out UIntPtr result);
    }
}
"@
    }
    $broadcast = [IntPtr]0xffff
    $settingChanged = 0x001A
    $abortIfHung = 0x0002
    $result = [UIntPtr]::Zero
    [void][RipleyEnvironment.NativeMethods]::SendMessageTimeout(
        $broadcast,
        $settingChanged,
        [UIntPtr]::Zero,
        "Environment",
        $abortIfHung,
        5000,
        [ref]$result
    )
}

try {
    Write-Host ""
    Write-Host "Ripley MCP setup for Codex" -ForegroundColor Cyan
    Write-Host "--------------------------"

    if ([string]::IsNullOrWhiteSpace($ApiKey)) {
        $ApiKey = Read-PrivateToken
    }
    $ApiKey = $ApiKey.Trim()
    if ($ApiKey.Length -lt 16 -or $ApiKey -match "\s") {
        throw "That connection key does not look valid. Ask Thomas for the bearer token and try again."
    }

    $configExisted = Test-Path -LiteralPath $configPath
    $oldContent = if ($configExisted) {
        [IO.File]::ReadAllText($configPath)
    }
    else {
        ""
    }
    $cleanContent = Remove-RipleySection -Content $oldContent
    $ripleySection = @"
[mcp_servers.$serverName]
url = "$serverUrl"
bearer_token_env_var = "$environmentName"
"@
    $newContent = if ([string]::IsNullOrWhiteSpace($cleanContent)) {
        $ripleySection + [Environment]::NewLine
    }
    else {
        $cleanContent + [Environment]::NewLine + [Environment]::NewLine +
            $ripleySection + [Environment]::NewLine
    }

    if ($WhatIf) {
        Write-Host "CHECK PASSED: the installer would save the key and register $serverUrl."
        exit 0
    }

    $health = Invoke-RestMethod -Method Get -Uri $healthUrl -Headers @{ "X-API-Key" = $ApiKey } -TimeoutSec 30
    if (-not $health.authenticated -or -not $health.form_60_available) {
        throw "The Ripley service answered, but its account connection is not ready."
    }

    if (-not (Test-Path -LiteralPath $configDirectory)) {
        New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
    }
    if (Test-Path -LiteralPath $configPath) {
        $backupPath = "$configPath.before-ripley"
        Copy-Item -LiteralPath $configPath -Destination $backupPath -Force
    }

    $previousUserToken = [Environment]::GetEnvironmentVariable($environmentName, "User")
    $changesApplied = $true
    [Environment]::SetEnvironmentVariable($environmentName, $ApiKey, "User")
    $env:RIPLEY_API_KEY = $ApiKey
    Send-EnvironmentRefresh
    [IO.File]::WriteAllText($configPath, $newContent, [Text.UTF8Encoding]::new($false))

    $codexCommand = Get-Command codex -ErrorAction SilentlyContinue
    if ($codexCommand) {
        & $codexCommand.Source mcp get $serverName *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "Codex could not read the new Ripley MCP registration."
        }
    }

    Write-Host ""
    Write-Host "SUCCESS: Ripley is connected to Codex." -ForegroundColor Green
    Write-Host "Close Codex completely, reopen it, and start a new chat."
    Write-Host "You can then say: Check my Ripley connection."
    exit 0
}
catch {
    if ($changesApplied) {
        [Environment]::SetEnvironmentVariable($environmentName, $previousUserToken, "User")
        Send-EnvironmentRefresh
        if (-not $configExisted) {
            Remove-Item -LiteralPath $configPath -Force -ErrorAction SilentlyContinue
        }
        else {
            [IO.File]::WriteAllText($configPath, $oldContent, [Text.UTF8Encoding]::new($false))
        }
    }
    Write-Host ""
    Write-Host "SETUP ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    $ApiKey = $null
    Remove-Item Env:RIPLEY_API_KEY -ErrorAction SilentlyContinue
}
