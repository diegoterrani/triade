#!/usr/bin/env bash
# Prepara o VPS Ubuntu/Debian.
# Não liga live_enabled e não cria DAYTRADE_LIVE_CONFIRM.
# As unidades nascem desabilitadas. Os agentes nascem em paper.
# Não chama loginctl enable-linger: isso fica para o checklist, na mão.
# O cripto usa o Python do Linux. B3 e NASDAQ usam um prefixo Wine cada.
#
# Uso:
#   bash scripts/linux/setup-triade.sh
#   bash scripts/linux/setup-triade.sh --units-only
#   TRIADE_UNIT_DIR=/tmp/units bash scripts/linux/setup-triade.sh --units-only --no-systemctl
set -euo pipefail

UNITS_ONLY=0
NO_SYSTEMCTL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --units-only) UNITS_ONLY=1 ;;
    --no-systemctl) NO_SYSTEMCTL=1 ;;
    -h|--help)
      echo "uso: scripts/linux/setup-triade.sh [--units-only] [--no-systemctl]"
      exit 0
      ;;
    *)
      echo "argumento desconhecido: $1" >&2
      exit 2
      ;;
  esac
  shift
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PY_VER="${TRIADE_WINDOWS_PYTHON:-3.12.8}"
CACHE="$HOME/.local/share/triade/cache"
UNIT_DIR="${TRIADE_UNIT_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}"

echo "Raiz: $ROOT"
echo "Python de Windows dentro do Wine: $PY_VER"

if [[ "$UNITS_ONLY" -eq 0 ]]; then
  if command -v apt-get >/dev/null 2>&1 && [[ "$(id -u)" -eq 0 ]]; then
    apt-get update
    apt-get install -y wine wine64 winetricks xvfb cabextract unzip wget ca-certificates python3 python3-venv python3-pip
  elif ! command -v wine >/dev/null 2>&1 || ! command -v Xvfb >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
    echo "Instale os pacotes e rode de novo:" >&2
    echo "  sudo apt-get install -y wine wine64 winetricks xvfb cabextract unzip wget ca-certificates python3 python3-venv python3-pip" >&2
    exit 1
  fi

  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e ".[dev]"
  if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "Criei .env a partir de .env.example. Preencha os logins fora do git."
  fi
  mkdir -p var/b3/logs var/crypto/logs var/nasdaq/logs "$CACHE"
fi

install_windows_python() {
  local name="$1"
  local prefix="$HOME/.local/share/triade/wine-$name"
  export WINEPREFIX="$prefix"
  export WINEARCH=win64
  export WINEDEBUG="${WINEDEBUG:--all}"
  mkdir -p "$prefix"
  echo "Prefixo $name: $prefix"
  xvfb-run -a wineboot --init
  local installer="$CACHE/python-${PY_VER}-amd64.exe"
  if [[ ! -f "$installer" ]]; then
    wget -O "$installer" "https://www.python.org/ftp/python/${PY_VER}/python-${PY_VER}-amd64.exe"
  fi
  xvfb-run -a wine "$installer" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_pip=1 "TargetDir=C:\\Python312"
  xvfb-run -a wine "C:\\Python312\\python.exe" -m pip install --upgrade pip
  xvfb-run -a wine "C:\\Python312\\python.exe" -m pip install MetaTrader5
}

if [[ "$UNITS_ONLY" -eq 0 ]]; then
  install_windows_python b3
  install_windows_python nasdaq
fi

write_unit() {
  local name="$1"
  local body="$2"
  mkdir -p "$UNIT_DIR"
  printf '%s\n' "$body" > "$UNIT_DIR/${name}.service"
  echo "unidade gravada, ainda desabilitada: $UNIT_DIR/${name}.service"
}

for spec in "b3:71" "nasdaq:72"; do
  name="${spec%%:*}"
  display="${spec##*:}"
  write_unit "triade-xvfb-$name" "[Unit]
Description=TRIADE Xvfb do terminal $name
[Service]
ExecStart=/usr/bin/Xvfb :${display} -screen 0 1280x800x24
Restart=on-failure
RestartSec=2
[Install]
WantedBy=default.target"

  # Sem StandardOutput=append: o Python do Wine aborta com WinError 6.
  # run-bridge.sh grava ${ROOT}/var/${name}/logs/bridge.log.
  write_unit "triade-bridge-$name" "[Unit]
Description=TRIADE ponte MT5 $name (Wine, 127.0.0.1)
After=triade-xvfb-${name}.service
Requires=triade-xvfb-${name}.service
[Service]
# O stdout deste processo nao pode ser um arquivo do systemd.
# O Python do Wine aborta com WinError 6. O wrapper grava o log.
WorkingDirectory=${ROOT}
ExecStart=${ROOT}/scripts/linux/run-bridge.sh ${name}
Restart=on-failure
RestartSec=5
StandardInput=null
[Install]
WantedBy=default.target"

  write_unit "triade-agent-$name" "[Unit]
Description=TRIADE agente $name em paper
After=triade-bridge-${name}.service
[Service]
WorkingDirectory=${ROOT}
ExecStart=${ROOT}/scripts/linux/run-agent.sh ${name} paper
Restart=on-failure
RestartSec=10
[Install]
WantedBy=default.target"
done

write_unit "triade-agent-crypto" "[Unit]
Description=TRIADE agente crypto em paper
[Service]
WorkingDirectory=${ROOT}
ExecStart=${ROOT}/scripts/linux/run-agent.sh crypto paper
Restart=on-failure
RestartSec=10
[Install]
WantedBy=default.target"

chmod +x "$ROOT/scripts/linux/run-agent.sh" "$ROOT/scripts/linux/run-bridge.sh" "$ROOT/scripts/linux/setup-triade.sh" "$ROOT/scripts/linux/wine_stdio.py"

if [[ "$NO_SYSTEMCTL" -eq 0 ]] && command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload || echo "systemctl --user falhou. Entre numa sessão de usuário e rode: systemctl --user daemon-reload"
  systemctl --user disable \
    triade-xvfb-b3 triade-bridge-b3 triade-agent-b3 \
    triade-xvfb-nasdaq triade-bridge-nasdaq triade-agent-nasdaq \
    triade-agent-crypto \
    >/dev/null 2>&1 || true
fi

cat <<EOF

Pronto para o paper. Nada foi colocado em live.
Linger não foi ativado. O boot fica para o checklist do README, na mão.
A ponte não manda o stdout do Wine para o systemd. O log é var/<agente>/logs/bridge.log.

Agora, em cada prefixo, instale o terminal e faça o login na mão:
  B3:  WINEPREFIX=\$HOME/.local/share/triade/wine-b3 xvfb-run -a wine instalador-mt5-da-xp.exe
       Se a XP não tiver MT5, use o instalador da Clear ou da Rico. Outro login, outro servidor.
  NASDAQ: WINEPREFIX=\$HOME/.local/share/triade/wine-nasdaq xvfb-run -a wine instalador-mt5-icmarkets.exe

Aponte mt5.terminal_path para o terminal64.exe de dentro daquele prefixo, por exemplo
  C:\\Program Files\\MetaTrader 5\\terminal64.exe
As portas já estão separadas: B3 18861, NASDAQ 18862, as duas em 127.0.0.1.

Checagem, com o agente parado:
  systemctl --user start triade-xvfb-b3 triade-bridge-b3
  .venv/bin/python -m daytrade.mt5bridge check --config configs/b3.yaml

Os agentes continuam desabilitados e em paper. O checklist do README é que autoriza a conta real.
EOF
