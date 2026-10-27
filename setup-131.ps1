#Requires -RunAsAdministrator
# One-time setup for the 3080 Ti laptop (.131): upgrade Ollama, set server options, let the normal user start/stop the service.
# Run from an ELEVATED PowerShell. Changes: C:\Ollama\bin (new), the "Ollama" NSSM service settings. Nothing is deleted.
$ErrorActionPreference = 'Stop'
$ver  = 'v0.40.10'
$want = 'd52aea2d323bdd324bf66a4b1226844aa5fb665cc5974fbcceceda1ce3d934eb'   # sha256 published by GitHub for this release asset
$zip  = 'C:\Ollama\dl\ollama-windows-amd64.zip'
New-Item -ItemType Directory -Force C:\Ollama\dl, C:\Ollama\logs | Out-Null

if (-not (Test-Path $zip) -or (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() -ne $want) {
    Write-Host "Downloading Ollama $ver (about 1.5 GB)..."
    curl.exe -sS -L -C - --retry 10 --retry-all-errors -o $zip "https://github.com/ollama/ollama/releases/download/$ver/ollama-windows-amd64.zip"
}
$got = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($got -ne $want) { throw "Checksum mismatch ($got), aborting before any change to the service." }
Write-Host "Checksum OK."

Expand-Archive $zip -DestinationPath C:\Ollama\bin -Force
$old = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\Ollama\Parameters').Application
Write-Host "Previous binary (rollback = nssm set Ollama Application <this path>): $old"

Stop-Service Ollama
$nssm = (Get-Command nssm).Source
& $nssm set Ollama Application C:\Ollama\bin\ollama.exe | Out-Null
& $nssm set Ollama AppParameters serve | Out-Null
& $nssm set Ollama AppEnvironmentExtra 'OLLAMA_HOST=0.0.0.0:11434' 'OLLAMA_MODELS=C:\Ollama\Models' 'OLLAMA_CONTEXT_LENGTH=16384' 'OLLAMA_MAX_LOADED_MODELS=1' 'OLLAMA_KEEP_ALIVE=30m' 'OLLAMA_FLASH_ATTENTION=1' 'OLLAMA_KV_CACHE_TYPE=q8_0' | Out-Null
& $nssm set Ollama AppStdout C:\Ollama\logs\ollama.out.log | Out-Null
& $nssm set Ollama AppStderr C:\Ollama\logs\ollama.err.log | Out-Null
& $nssm set Ollama AppRotateFiles 1 | Out-Null

# Allow the normal user account to start/stop (not reconfigure) the service.
$sid = (New-Object Security.Principal.NTAccount('DESKTOP-SOL57OK\user')).Translate([Security.Principal.SecurityIdentifier]).Value
$sd = (sc.exe sdshow Ollama | Where-Object { $_.Trim() }) -join ''
if ($sd -notmatch [regex]::Escape($sid) -and $sd -match '^(D:.*?)(S:.*)?$') {
    sc.exe sdset Ollama ($matches[1] + "(A;;RPWPLCLORC;;;$sid)" + $matches[2]) | Out-Null
}

Start-Service Ollama
Start-Sleep 6
Write-Host ("Service: " + (Get-Service Ollama).Status)
Write-Host ("Version: " + (Invoke-RestMethod http://127.0.0.1:11434/api/version).version)
