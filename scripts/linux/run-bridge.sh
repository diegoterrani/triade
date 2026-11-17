#!/usr/bin/env bash
# Um terminal, um prefixo Wine, uma porta em 127.0.0.1.
# Uso: scripts/linux/run-bridge.sh b3
set -euo pipefail

AGENT="${1:-}"
case "$AGENT" in
  b3) DISPLAY_NUM=71 ;;
  nasdaq) DISPLAY_NUM=72 ;;
  *) echo "a ponte é só da B3 e do NASDAQ" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/.venv/bin/python"
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

SOCKET="/tmp/.X11-unix/X${DISPLAY_NUM}"
if [[ ! -S "$SOCKET" ]]; then
  echo "Display :${DISPLAY_NUM} ausente. Suba triade-xvfb-${AGENT} antes da ponte." >&2
  exit 1
fi

PREFIX="${TRIADE_WINEPREFIX:-$HOME/.local/share/triade/wine-$AGENT}"
WIN_PY="C:\\Python312\\python.exe"
SERVER="$(readlink -f "$ROOT/scripts/linux/mt5_bridge_server.py")"
WIN_SERVER="Z:${SERVER//\//\\}"
mkdir -p "$ROOT/var/$AGENT/logs"

export WINEPREFIX="$PREFIX"
export WINEARCH=win64
export WINEDEBUG="${WINEDEBUG:--all}"
export DISPLAY=":${DISPLAY_NUM}"

echo "ponte $AGENT em 127.0.0.1:${PORT} prefixo $PREFIX display :${DISPLAY_NUM}"
exec wine "$WIN_PY" -u "$WIN_SERVER" --host 127.0.0.1 --port "$PORT"
