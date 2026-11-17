# Watcher de um agente TRIADE. Nao religa o Python enquanto o kill existir.
# Uso: powershell -File scripts\windows\run-agent.ps1 -Agent b3 -Mode paper
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("b3", "crypto", "nasdaq")]
    [string]$Agent,
    [ValidateSet("paper", "live")]
    [string]$Mode = "paper"
)

$ErrorActionPreference = "Continue"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Venv ausente em $Python. Rode scripts\windows\setup-triade.ps1 primeiro."
    exit 1
}

$KillAll = Join-Path $Root "var\KILL_ALL"
$KillAgent = Join-Path $Root "var\$Agent\KILL"
$LogDir = Join-Path $Root "var\$Agent\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Write-Host "TRIADE $Agent modo $Mode. Log do processo: $LogDir\$Mode.jsonl"

while ($true) {
    if ((Test-Path $KillAll) -or (Test-Path $KillAgent)) {
        Write-Host "$(Get-Date -Format o) kill ativo. O agente nao reinicia enquanto o arquivo existir."
        Start-Sleep -Seconds 15
        continue
    }
    & $Python -m "daytrade.$Agent" $Mode
    $code = $LASTEXITCODE
    Write-Host "$(Get-Date -Format o) processo $Agent saiu com codigo $code. Nova tentativa em 10s."
    Start-Sleep -Seconds 10
}
