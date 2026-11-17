# Prepara o VPS Windows perto de Sao Paulo.
# Nao liga live_enabled e nao cria a variavel DAYTRADE_LIVE_CONFIRM.
# As tarefas nascem desabilitadas e em modo paper.
# Uso, no PowerShell, na raiz do projeto:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\setup-triade.ps1
param(
    [string]$PythonExe = "py"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $Root

Write-Host "Raiz: $Root"
Write-Host "Instale o Python 3.12 de 64 bits em python.org se 'py -3.12' falhar."
Write-Host "O wheel MetaTrader5 so existe para Windows amd64, na mesma maquina do terminal."

& $PythonExe -3.12 -m venv .venv
if ($LASTEXITCODE -ne 0) {
    throw "Nao consegui criar o venv com $PythonExe -3.12"
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -e ".[dev,mt5]"
if ($LASTEXITCODE -ne 0) {
    throw "pip install falhou. Sem o extra mt5 o backtest ainda roda; o terminal nao."
}

$EnvExample = Join-Path $Root ".env.example"
$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item $EnvExample $EnvFile
    Write-Host "Criei .env a partir de .env.example. Preencha os logins fora do git."
}

foreach ($name in @("b3", "crypto", "nasdaq")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "var\$name\logs") | Out-Null
}

$Watcher = Join-Path $PSScriptRoot "run-agent.ps1"
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
foreach ($name in @("b3", "crypto", "nasdaq")) {
    $taskName = "TRIADE-$name"
    $argument = "-NoProfile -ExecutionPolicy Bypass -File `"$Watcher`" -Agent $name -Mode paper"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $Principal -Force | Out-Null
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    Write-Host "Tarefa $taskName criada DESABILITADA, modo paper."
}

Write-Host ""
Write-Host "Terminais, cada um no proprio diretorio:"
Write-Host "  B3: MT5 da XP. Se a XP nao oferecer MT5, Clear ou Rico (mesmo grupo, outro login e outro servidor)."
Write-Host "  NASDAQ: MT5 da IC Markets, outro terminal64.exe, magic 26011702."
Write-Host "Aponte mt5.terminal_path de cada YAML para o executavel daquele terminal."
Write-Host "Nao aponte os dois agentes para o mesmo terminal64.exe."
Write-Host "live_enabled continua false. O checklist do README e que autoriza a conta real."
