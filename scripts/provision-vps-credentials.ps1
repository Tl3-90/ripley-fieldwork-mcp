$ErrorActionPreference = 'Stop'

$credential = Get-Credential -Message 'Enter the Ripley account email and password. They will be sent directly to the Hetzner VPS.'
if ($null -eq $credential) {
    throw 'Credential entry was cancelled.'
}

$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($credential.Password)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    $payload = @{
        username = $credential.UserName
        password = $plainPassword
    } | ConvertTo-Json -Compress
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload))

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = 'ssh'
    $startInfo.ArgumentList.Add('-o')
    $startInfo.ArgumentList.Add('BatchMode=yes')
    $startInfo.ArgumentList.Add('root@87.99.147.219')
    $startInfo.ArgumentList.Add('python3 /opt/ripley-api/scripts/store-secrets.py')
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($startInfo)
    $process.StandardInput.WriteLine($encoded)
    $process.StandardInput.Close()
    $output = $process.StandardOutput.ReadToEnd()
    $errorOutput = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        throw "VPS credential provisioning failed: $errorOutput"
    }
    if ($output.Trim() -ne 'RIPLEY_SECRETS_STORED') {
        throw 'VPS did not confirm credential storage.'
    }
    Write-Host 'Ripley credentials were stored on the VPS without writing them locally.'
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    $plainPassword = $null
    $payload = $null
    $encoded = $null
    $credential = $null
}
