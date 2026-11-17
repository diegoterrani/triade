#!/usr/bin/env bash
# Sobe um agente e não religa o Python enquanto o kill existir.
# Uso: scripts/linux/run-agent.sh b3 paper
set -euo pipefail

AGENT="${1:-}"
MODE="${2:-paper}"
case "$AGENT" in
  b3|crypto|nasdaq) ;;
  *) echo "agente inválido: use b3, crypto ou nasdaq" >&2; exit 2 ;;
esac
case "$MODE" in
  paper|live) ;;
  *) echo "modo inválido: paper ou live" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "venv ausente em $PY. Rode scripts/linux/setup-triade.sh primeiro." >&2
  exit 1
fi
mkdir -p "$ROOT/var/$AGENT/logs"
echo "TRIADE $AGENT modo $MODE. Log: var/$AGENT/logs/$MODE.jsonl"

while true; do
  if [[ -e "$ROOT/var/KILL_ALL" || -e "$ROOT/var/$AGENT/KILL" ]]; then
    echo "$(date -Is) kill ativo. $AGENT não reinicia enquanto o arquivo existir."
    sleep 15
    continue
  fi
  set +e
  "$PY" -m "daytrade.$AGENT" "$MODE"
  code=$?
  set -e
  echo "$(date -Is) processo $AGENT saiu com código $code. Nova tentativa em 10s."
  sleep 10
done
