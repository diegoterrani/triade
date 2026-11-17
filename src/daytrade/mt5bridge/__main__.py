"""Confere se a ponte local responde. Não envia ordem.

    python -m daytrade.mt5bridge check --config configs/b3.yaml
    python -m daytrade.mt5bridge check --config configs/b3.yaml --init
"""

from __future__ import annotations

import argparse
import json
import sys

from daytrade.common.config import load_config, require_env
from daytrade.common.errors import Disconnect, SafetyError
from daytrade.common.mt5_bridge import BridgeClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="daytrade.mt5bridge", description="Saúde da ponte MT5.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("check", help="Ping na ponte. --init também abre o terminal.")
    check.add_argument("--config", default=None)
    check.add_argument("--host", default=None)
    check.add_argument("--port", type=int, default=None)
    check.add_argument("--timeout", type=float, default=None)
    check.add_argument("--init", action="store_true", help="Inicializa o terminal e lê a equity. Pare o agente antes.")
    args = parser.parse_args(argv)
    try:
        host, port, timeout, cfg = _target(args)
        client = BridgeClient(host, port, timeout=timeout, heartbeat=timeout)
        client.connect()
        report: dict[str, object] = {"ok": True, "host": host, "port": port, "pong": True}
        if args.init:
            if cfg is None:
                raise SafetyError("--init precisa de --config")
            mt5_cfg = cfg["mt5"]
            ok = client.initialize(
                path=str(mt5_cfg.get("terminal_path") or ""),
                login=int(require_env(mt5_cfg["login_env"])),
                password=require_env(mt5_cfg["password_env"]),
                server=require_env(mt5_cfg["server_env"]),
            )
            info = client.account_info() if ok else None
            report["initialized"] = ok
            report["equity"] = None if info is None else info.equity
            if not ok:
                report["ok"] = False
                report["last_error"] = client.last_error()
        print(json.dumps(report, ensure_ascii=False))
        client.close()
        return 0 if report["ok"] else 2
    except (SafetyError, Disconnect, ValueError, OSError, KeyError) as exc:
        print(f"erro: {exc}")
        return 2


def _target(args: argparse.Namespace) -> tuple[str, int, float, dict | None]:
    cfg = load_config(args.config) if args.config else None
    mt5_cfg = (cfg or {}).get("mt5") or {}
    host = args.host or mt5_cfg.get("bridge_host") or "127.0.0.1"
    port = args.port if args.port is not None else int(mt5_cfg.get("bridge_port") or 0)
    timeout = args.timeout if args.timeout is not None else float(mt5_cfg.get("bridge_timeout_seconds") or 5)
    if not port:
        raise SafetyError("informe --port ou um config com mt5.bridge_port")
    return str(host), int(port), float(timeout), cfg


if __name__ == "__main__":
    sys.exit(main())
