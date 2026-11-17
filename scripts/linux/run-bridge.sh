#!/usr/bin/env bash
# Um terminal, um prefixo Wine, uma porta em 127.0.0.1.
# Uso: scripts/linux/run-bridge.sh b3
#      scripts/linux/run-bridge.sh --print-launch b3
#
# O Python de Windows não herda o stdout do systemd. wine_stdio.py põe o
# Wine num console (pty) e um processo do Linux anexa a saída em
# var/<agente>/logs/bridge.log. O stdin desse processo vem de /dev/null.
set -euo pipefail

PRINT_LAUNCH=0
if [[ "${1:-}" == "--print-launch" ]]; then
  PRINT_LAUNCH=1
  shift
fi

AGENT="${1:-}"
case "$AGENT" in
  b3) DISPLAY_NUM=71 ;;
  nasdaq) DISPLAY_NUM=72 ;;
  *) echo "a ponte é só da B3 e do NASDAQ" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -n "${TRIADE_PY:-}" ]]; then
  PY="$TRIADE_PY"
else
  PY="$ROOT/.venv/bin/python"
fi
if [[ ! -x "$PY" ]]; then
  echo "venv ausente. Rode scripts/linux/setup-triade.sh primeiro." >&2
  exit 1
fi

PORT="$(TRIADE_ROOT="$ROOT" TRIADE_AGENT="$AGENT" "$PY" - <<'PY'
import os
from pathlib import Path

import yaml

root = Path(os.environ["TRIADE_ROOT"])
agent = os.environ["TRIADE_AGENT"]
cfg = yaml.safe_load((root / "configs" / f"{agent}.yaml").read_text(encoding="utf-8"))
mt5 = cfg["mt5"]
if mt5.get("transport") != "bridge":
    raise SystemExit("mt5.transport deste agente não é bridge")
if mt5.get("bridge_host") != "127.0.0.1":
    raise SystemExit("mt5.bridge_host tem de ser 127.0.0.1")
port = int(mt5["bridge_port"])
if not 1 <= port <= 65535:
    raise SystemExit("porta inválida")
print(port)
PY
)"

PREFIX="${TRIADE_WINEPREFIX:-$HOME/.local/share/triade/wine-$AGENT}"
WIN_PY="C:\\Python312\\python.exe"
SERVER="$(readlink -f "$ROOT/scripts/linux/mt5_bridge_server.py")"
WIN_SERVER="Z:${SERVER//\//\\}"
LOG="$ROOT/var/$AGENT/logs/bridge.log"
export WINEPREFIX="$PREFIX"
export WINEARCH=win64
export WINEDEBUG="${WINEDEBUG:--all}"
export DISPLAY=":${DISPLAY_NUM}"
export PYTHONUNBUFFERED=1

LAUNCH=(wine "$WIN_PY" -u "$WIN_SERVER" --host 127.0.0.1 --port "$PORT")

if [[ "$PRINT_LAUNCH" -eq 1 ]]; then
  printf 'host=127.0.0.1\n'
  printf 'port=%s\n' "$PORT"
  printf 'display=:%s\n' "$DISPLAY_NUM"
  printf 'stdin=/dev/null\n'
  printf 'stdio=pty\n'
  printf 'log=%s\n' "$LOG"
  printf 'logger=linux\n'
  printf 'pythonunbuffered=%s\n' "$PYTHONUNBUFFERED"
  printf 'winedebug=%s\n' "$WINEDEBUG"
  printf 'argv='
  printf '%q ' "${LAUNCH[@]}"
  printf '\n'
  exit 0
fi

SOCKET="/tmp/.X11-unix/X${DISPLAY_NUM}"
if [[ ! -S "$SOCKET" ]]; then
  echo "Display :${DISPLAY_NUM} ausente. Suba triade-xvfb-${AGENT} antes da ponte." >&2
  exit 1
fi

mkdir -p "$ROOT/var/$AGENT/logs"
printf '%s\n' "ponte $AGENT em 127.0.0.1:${PORT} prefixo $PREFIX display :${DISPLAY_NUM}" >>"$LOG"
exec "$PY" "$ROOT/scripts/linux/wine_stdio.py" "$LOG" "${LAUNCH[@]}"
