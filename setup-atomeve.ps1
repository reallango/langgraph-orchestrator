#Requires -RunAsAdministrator
# One-time setup for AtomEve (RTX 5070 Ti): upgrade the NSSM-managed Ollama service to v0.40.10 (same as the other
# workers) and add flash attention + 8-bit KV cache. Keeps the existing models folder and other settings.
# Run ON AtomEve from an elevated PowerShell, or from the other PC with:
#   Invoke-Command -ComputerName AtomEve -Credential (Get-Credential 'ATOMEVE\aiadmin') -FilePath .\setup-atomeve.ps1
$ErrorActionPreference = 'Stop'
$ver  = 'v0.40.10'
$want = 'd52aea2d323bdd324bf66a4b1226844aa5fb665cc5974fbcceceda1ce3d934eb'   # GitHub-published sha256 of the asset
$root = 'C:\Ollama'
$zip  = "$root\dl\ollama-windows-amd64.zip"
New-Item -ItemType Directory -Force "$root\dl", "$root\logs" | Out-Null

$svcKey = 'HKLM:\SYSTEM\CurrentControlSet\Services\Ollama'
$nssm = ((Get-ItemProperty $svcKey).ImagePath -replace '"', '').Trim()
if (-not (Test-Path $nssm)) { throw "Could not find the NSSM executable for the Ollama service ($nssm)." }
$params = Get-ItemProperty "$svcKey\Parameters"
Write-Host "NSSM: $nssm"
Write-Host "Current binary (rollback = nssm set Ollama Application <this>): $($params.Application)"

if (-not (Test-Path $zip) -or (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() -ne $want) {
    Write-Host "Downloading Ollama $ver (about 1.5 GB)..."
    curl.exe -sS -L -C - --retry 10 --retry-all-errors -o $zip "https://github.com/ollama/ollama/releases/download/$ver/ollama-windows-amd64.zip"
}
if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() -ne $want) { throw 'Checksum mismatch; nothing was changed.' }
Write-Host 'Checksum OK.'
Expand-Archive $zip -DestinationPath "$root\bin" -Force

# keep existing environment entries, override/add the ones we need
$vars = @{}
foreach ($line in @($params.AppEnvironmentExtra)) { if ($line -match '^([^=]+)=(.*)$') { $vars[$Matches[1]] = $Matches[2] } }
$vars['OLLAMA_HOST'] = '0.0.0.0:11434'
if (-not $vars.ContainsKey('OLLAMA_MODELS')) { $vars['OLLAMA_MODELS'] = 'D:\AI\Models' }
$vars['OLLAMA_MAX_LOADED_MODELS'] = '1'
$vars['OLLAMA_KEEP_ALIVE'] = '30m'
$vars['OLLAMA_FLASH_ATTENTION'] = '1'
$vars['OLLAMA_KV_CACHE_TYPE'] = 'q8_0'
if (-not $vars.ContainsKey('OLLAMA_CONTEXT_LENGTH')) { $vars['OLLAMA_CONTEXT_LENGTH'] = '32768' }
Write-Host "Models folder: $($vars['OLLAMA_MODELS'])"

Stop-Service Ollama -ErrorAction SilentlyContinue
& $nssm set Ollama Application "$root\bin\ollama.exe" | Out-Null
& $nssm set Ollama AppParameters serve | Out-Null
& $nssm set Ollama AppEnvironmentExtra ($vars.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) | Out-Null
& $nssm set Ollama AppStdout "$root\logs\ollama.out.log" | Out-Null
& $nssm set Ollama AppStderr "$root\logs\ollama.err.log" | Out-Null
Start-Service Ollama
Start-Sleep 6
Write-Host ("Service: " + (Get-Service Ollama).Status)
Write-Host ("Version: " + (Invoke-RestMethod http://127.0.0.1:11434/api/version).version)
Write-Host ("Free space on models drive: {0:N0} GB" -f ((Get-PSDrive ($vars['OLLAMA_MODELS'].Substring(0,1))).Free / 1GB))
